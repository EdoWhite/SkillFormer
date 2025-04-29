import argparse
import torch
import av
import os
import json
import numpy as np
from functools import partial
from sklearn.metrics import accuracy_score
from PIL import Image
from transformers.processing_utils import ProcessorMixin
from transformers.tokenization_utils import BatchEncoding

from transformers import (
    TimesformerModel, AutoImageProcessor, TrainingArguments, Trainer,
    PreTrainedModel, PretrainedConfig
)
from peft import LoraConfig, get_peft_model, PeftModel

# Setting device and constants
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
VISION_ENCODER = "facebook/timesformer-base-finetuned-k600"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

class AttentiveProjector(torch.nn.Module):
    def __init__(self, 
                 input_dim=768, 
                 hidden_dim=1024, 
                 out_dim=576, 
                 num_heads=4,
                 dropout=0.1,
                 use_gate=True,
                 learn_stats=True,
                 init_text_mean=0.0007, 
                 init_text_std=0.1168):
        """
        Enhanced projector with multi-head attention, temporal modeling, and learnable statistics.
        """
        super().__init__()
        
        # Multi-head attention for view integration
        self.view_norm = torch.nn.LayerNorm(input_dim)
        self.view_attn = torch.nn.MultiheadAttention(
            embed_dim=input_dim,
            num_heads=num_heads,
            dropout=dropout,
            batch_first=True
        )
        
        # Feature transformation
        self.proj1 = torch.nn.Linear(input_dim, hidden_dim)
        self.act = torch.nn.GELU()
        self.norm1 = torch.nn.LayerNorm(hidden_dim)
        self.dropout = torch.nn.Dropout(dropout)
        
        # Gating mechanism
        self.use_gate = use_gate
        if use_gate:
            self.gate = torch.nn.Sequential(
                torch.nn.Linear(hidden_dim, hidden_dim),
                torch.nn.Sigmoid()
            )
            
        # Final projection to LLM dimension
        self.proj2 = torch.nn.Linear(hidden_dim, out_dim)
        self.norm_final = torch.nn.LayerNorm(out_dim)
        
        # Statistics for normalization - learnable or fixed
        self.learn_stats = learn_stats
        if learn_stats:
            self.text_mean = torch.nn.Parameter(torch.tensor(init_text_mean))
            self.text_std = torch.nn.Parameter(torch.tensor(init_text_std))
        else:
            self.register_buffer("text_mean", torch.tensor(init_text_mean))
            self.register_buffer("text_std", torch.tensor(init_text_std))
        
    def forward(self, video_feats):  # (B, V, D)
        B, V, D = video_feats.shape
        
        # Apply layer norm to input
        video_feats = self.view_norm(video_feats)
        
        # Multi-head self-attention across views
        # Each view attends to all other views
        attn_output, _ = self.view_attn(
            query=video_feats,
            key=video_feats,
            value=video_feats
        )
        
        # Average pooling across views (can be learned by attention)
        fused_feats = attn_output.mean(dim=1)  # (B, D)
        
        # First projection
        hidden = self.proj1(fused_feats)  # (B, hidden_dim)
        hidden = self.act(hidden)
        hidden = self.norm1(hidden)
        hidden = self.dropout(hidden)
        
        # Apply gating if enabled
        if self.use_gate:
            gate_values = self.gate(hidden)
            hidden = hidden * gate_values
            
        # Final projection and normalization
        output = self.proj2(hidden)  # (B, out_dim)
        output = self.norm_final(output)
        
        # Normalize to match text embedding statistics
        output = self.normalize_to_text_stats(output)
        
        return output
    
    def normalize_to_text_stats(self, video_emb):
        # Center to zero mean
        video_emb = video_emb - video_emb.mean(dim=-1, keepdim=True)
        
        # Scale to unit variance 
        video_emb = video_emb / (video_emb.std(dim=-1, keepdim=True) + 1e-6)
        
        # Apply learned/fixed text statistics
        video_emb = video_emb * self.text_std
        video_emb = video_emb + self.text_mean
        
        return video_emb

class VideoProcessor(ProcessorMixin):
    attributes = ["image_processor"]
    image_processor_class = ("BaseImageProcessor",)
    
    def __init__(self, image_processor):
        if image_processor is None:
            raise ValueError("You must provide an image_processor.")

        self.image_processor = image_processor
        super().__init__(image_processor)    
    
    def __call__(self, videos=None, return_tensors=None, **kwargs):
        video_tensors = []
        for example_videos in videos:  # For each sample (V video)
            processed_videos = []
            for video in example_videos:  # Process each view
                processed = self.image_processor(list(video), return_tensors=return_tensors)["pixel_values"]
                processed_videos.append(processed.squeeze(0))  # (T, C, H, W)
            
            example_tensor = torch.stack(processed_videos)  # (V, T, C, H, W)
            video_tensors.append(example_tensor)

        video_tensor = torch.stack(video_tensors)  # (B, V, T, C, H, W)

        encoding = BatchEncoding(
            data={"pixel_values": video_tensor},
            tensor_type=return_tensors
        )
        return encoding
    
class VideoClassifierConfig(PretrainedConfig):
    """Configuration class for VideoClassifier."""
    model_type = "video_classifier"

    def __init__(
        self,
        vision_encoder_id="facebook/timesformer-base-finetuned-k600",
        num_frames=16,
        num_classes=4,
        num_views=1,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.vision_encoder_id = vision_encoder_id
        self.num_frames = num_frames
        self.num_classes = num_classes
        self.num_views = num_views

class VideoClassifier(PreTrainedModel):
    """Video classification model using TimesFormer with LoRA fine-tuning."""
    config_class = VideoClassifierConfig
    
    def __init__(self, config):
        super().__init__(config)
        
        self.num_views = config.num_views
        self.num_frames = config.num_frames
        self.num_classes = config.num_classes
        
        # Load the image processor for TimesFormer
        self.image_processor = AutoImageProcessor.from_pretrained(config.vision_encoder_id)
        
        # First load the TimesFormer model with default parameters
        self.vision_encoder = TimesformerModel.from_pretrained(
            config.vision_encoder_id,
            torch_dtype=torch.float16,
        )
        
        # Modify the time embeddings if needed
        if self.num_frames != 8:  # Default is 8 frames
            self._interpolate_time_embeddings(self.num_frames)
            # Update the config after modifying time embeddings
            self.vision_encoder.config.num_frames = self.num_frames
        
        target_modules = [
            "attention.attention.qkv",
            "attention.output.dense",
            "temporal_attention.attention.qkv",
            "temporal_attention.output.dense",
            "intermediate.dense",
            "output.dense",
            "temporal_dense"
        ]
                
        # LoRA configuration for TimesFormer
        lora_config = LoraConfig(
            r=16,
            lora_alpha=32,
            lora_dropout=0.1,
            bias="none",
            target_modules=target_modules
        )
        
        # Apply LoRA to vision encoder
        self.vision_encoder = get_peft_model(self.vision_encoder, lora_config)
        self.vision_encoder.gradient_checkpointing_enable()
        
        self.projector = VideoProjector(
            input_dim=768,
            hidden_dim=1024,
            out_dim=768,
            num_heads=12,
            use_gate=True,
            learn_stats=True
        )
        
        # Classification head
        self.classifier = torch.nn.Linear(768, self.num_classes)
        
        # Print trainable parameters
        self.print_trainable_parameters()
    
    def _interpolate_time_embeddings(self, target_frames):
        """
        Properly interpolate time embeddings to support different number of frames.
        """
        print(f"Interpolating time embeddings from 8 to {target_frames} frames")
        
        # Get the structure of time_embeddings
        # In TimesFormer, time_embeddings is a Parameter not a weight
        # We need to directly access it
        
        # First, check if we have direct access to time_embeddings
        if hasattr(self.vision_encoder, 'embeddings') and hasattr(self.vision_encoder.embeddings, 'time_embeddings'):
            time_embeddings = self.vision_encoder.embeddings.time_embeddings
            print("Found time_embeddings at vision_encoder.embeddings.time_embeddings")
        # Alternatively, try to find it through model attribute
        elif hasattr(self.vision_encoder, 'model') and hasattr(self.vision_encoder.model, 'embeddings') and hasattr(self.vision_encoder.model.embeddings, 'time_embeddings'):
            time_embeddings = self.vision_encoder.model.embeddings.time_embeddings
            print("Found time_embeddings at vision_encoder.model.embeddings.time_embeddings")
        else:
            # If we still can't find it, try to search through all parameters
            found = False
            for name, param in self.vision_encoder.named_parameters():
                if 'time_embed' in name.lower():
                    time_embeddings = param
                    print(f"Found time_embeddings at {name}")
                    found = True
                    break
            
            if not found:
                raise ValueError("Could not find time embeddings in the model")
        
        # Get the original time embeddings shape
        orig_size = time_embeddings.shape
        print(f"Original time embeddings shape: {orig_size}")
        
        if orig_size[0] == target_frames:
            return  # No need to interpolate
        
        # Create new embeddings with target frame count
        # We're assuming the shape is either [8, hidden_dim] or [1, 8, hidden_dim]
        if len(orig_size) == 2:
            hidden_dim = orig_size[1]
            orig_frames = orig_size[0]
            new_time_embeddings = torch.nn.Parameter(
                torch.zeros(target_frames, hidden_dim),
                requires_grad=True
            )
        else:  # len(orig_size) == 3
            hidden_dim = orig_size[2]
            orig_frames = orig_size[1]
            new_time_embeddings = torch.nn.Parameter(
                torch.zeros(1, target_frames, hidden_dim),
                requires_grad=True
            )
        
        # Calculate scaling factors
        scale = target_frames / orig_frames
        
        # Apply linear interpolation
        if len(orig_size) == 2:
            for t in range(target_frames):
                # Find the corresponding position in original embeddings
                orig_t = min(t / scale, orig_frames - 1)
                # Get the integer positions for interpolation
                t_floor = int(orig_t)
                t_ceil = min(t_floor + 1, orig_frames - 1)
                # Calculate the fractional part for weighting
                t_frac = orig_t - t_floor
                
                # Linear interpolation
                new_time_embeddings.data[t] = (1 - t_frac) * time_embeddings.data[t_floor] + t_frac * time_embeddings.data[t_ceil]
        else:  # len(orig_size) == 3
            for t in range(target_frames):
                # Find the corresponding position in original embeddings
                orig_t = min(t / scale, orig_frames - 1)
                # Get the integer positions for interpolation
                t_floor = int(orig_t)
                t_ceil = min(t_floor + 1, orig_frames - 1)
                # Calculate the fractional part for weighting
                t_frac = orig_t - t_floor
                
                # Linear interpolation
                new_time_embeddings.data[0, t] = (1 - t_frac) * time_embeddings.data[0, t_floor] + t_frac * time_embeddings.data[0, t_ceil]
        
        # Replace the original embeddings with the new ones
        # We need to check how to assign this properly
        if hasattr(self.vision_encoder, 'embeddings') and hasattr(self.vision_encoder.embeddings, 'time_embeddings'):
            self.vision_encoder.embeddings.time_embeddings = new_time_embeddings
        elif hasattr(self.vision_encoder, 'model') and hasattr(self.vision_encoder.model, 'embeddings') and hasattr(self.vision_encoder.model.embeddings, 'time_embeddings'):
            self.vision_encoder.model.embeddings.time_embeddings = new_time_embeddings
        
        print(f"Time embeddings interpolated from {orig_frames} to {target_frames} frames")
    
    def print_trainable_parameters(self):
        """Print number of trainable parameters."""
        trainable = 0
        total = 0
        for _, param in self.named_parameters():
            total += param.numel()
            if param.requires_grad:
                trainable += param.numel()
        print(f"Trainable: {trainable:,} | Total: {total:,} | %: {100*trainable/total:.2f}")
    
    def forward(self, pixel_values=None, labels=None):
        """Forward pass of the model."""
        B, V, T, C, H, W = pixel_values.shape
        
        # Reshape to combine batch and views
        pixel_values = pixel_values.reshape(B * V, T, C, H, W)
        
        # Extract features
        outputs = self.vision_encoder(pixel_values=pixel_values)
        
        # Pooling: mean over the sequence dimension
        pooled_output = outputs.last_hidden_state.mean(dim=1)  # (B*V, 768)
        
        # Reshape to separate batch and views
        pooled_output = pooled_output.reshape(B, V, -1)  # (B, V, 768)
        
        projected = self.projector(pooled_output) # (B, D)
        
        # Average over the views
        # pooled_output = pooled_output.mean(dim=1)  # (B, 768)
        
        # Classification
        logits = self.classifier(projected)  # (B, num_classes)
        
        loss = None
        if labels is not None:
            loss_fn = torch.nn.CrossEntropyLoss()
            loss = loss_fn(logits, labels)
        
        return {"loss": loss, "logits": logits} if loss is not None else {"logits": logits}
    
    def feature_extract(self, pixel_values):
        """Extract features without classification, for use as a feature extractor."""
        B, V, T, C, H, W = pixel_values.shape
        
        # Reshape to combine batch and views
        pixel_values = pixel_values.reshape(B * V, T, C, H, W)
        
        # Extract features
        with torch.no_grad():
            outputs = self.vision_encoder(pixel_values=pixel_values)
        
        # Pooling: mean over the sequence dimension
        pooled_output = outputs.last_hidden_state.mean(dim=1)  # (B*V, 768)
        
        # Reshape to separate batch and views
        pooled_output = pooled_output.reshape(B, V, -1)  # (B, V, 768)
        
        # Average over the views
        pooled_output = pooled_output.mean(dim=1)  # (B, 768)
        
        return pooled_output

class VideoDataset(torch.utils.data.Dataset):
    """Dataset for video classification."""
    def __init__(self, annotation_path, camera_indices=None, video_root=None, num_frames=16):
        self.camera_indices = camera_indices if camera_indices is not None else [0]
        self.annotation_path = annotation_path
        self.video_root = video_root
        self.num_frames = num_frames
        
        # Load annotations
        with open(self.annotation_path) as f:
            self.annotations = [json.loads(line) for line in f if all(k in json.loads(line) for k in ["video_paths", "proficiency_level"])]
        
        # Create label mapping
        self.labels = {"Novice": 0, "Early Expert": 1, "Intermediate Expert": 2, "Late Expert": 3}
    
    def __len__(self):
        return len(self.annotations)
    
    def __getitem__(self, idx):
        ann = self.annotations[idx]
        videos = []
        
        try:
            video_paths = ann["video_paths"]
            for cam_idx in self.camera_indices:
                if cam_idx >= len(video_paths):
                    # Skip if camera index is out of bounds
                    continue
                
                selected_path = os.path.join(self.video_root, video_paths[cam_idx].replace("frame_aligned_videos", "frame_aligned_videos/downscaled/448"))
                with av.open(selected_path) as container:
                    indices = sample_frame_indices(self.num_frames, 4, container.streams.video[0].frames)
                    video = read_video_pyav(container, indices)
                videos.append(video)
            
            # If no videos were loaded, raise an exception
            if not videos:
                raise ValueError(f"No videos were loaded for annotation {idx}")
            
            label = self.labels.get(ann['proficiency_level'].title(), 0)
            
            return {
                'videos': videos,  # List of V videos
                'label': label
            }
        except Exception as e:
            # Return a default item in case of error
            print(f"Error processing video_paths: {str(e)}")
            # Return first item as a fallback
            return self[0] if idx != 0 else None

def collate_fn(examples, video_processor):
    """Collate function for the dataloader."""
    # Filter out None examples
    examples = [ex for ex in examples if ex is not None]
    
    if not examples:
        return None  # Return None if no valid examples are found
    
    all_videos = []
    labels = []
    
    for ex in examples:
        all_videos.append(ex["videos"])
        labels.append(ex["label"])
    
    # Use the video processor to handle the processing of videos
    # Note that the video processor expects a list of lists of videos
    # where the outer list is the batch, and the inner list is the views
    batch = video_processor(videos=all_videos, return_tensors="pt")
    
    # Add labels to the batch
    batch["labels"] = torch.tensor(labels, dtype=torch.long)
    
    return batch

def compute_metrics(eval_pred):
    """Compute metrics for evaluation."""
    predictions = eval_pred.predictions.argmax(-1)
    return {"accuracy": accuracy_score(eval_pred.label_ids, predictions)}

def read_video_pyav(container, indices):
    """
    Decodes the video with PyAV decoder.
    Args:
        container (av.container.input.InputContainer): PyAV container.
        indices (list): List of frame indices to decode.
    Returns:
        np.ndarray: Array of decoded frames of shape (num_frames, height, width, 3).
    """
    frames = []
    container.seek(0)
    start_index = indices[0]
    end_index = indices[-1]
    for i, frame in enumerate(container.decode(video=0)):
        if i > end_index:
            break
        if i >= start_index and i in indices:
            frames.append(frame)
    return np.stack([x.to_ndarray(format="rgb24") for x in frames])

def sample_frame_indices(clip_len, frame_sample_rate, seg_len):
    """
    Samples a given number of frame indices from the video.
    Args:
        clip_len (int): Total number of frames to sample.
        frame_sample_rate (int): Sample every n-th frame.
        seg_len (int): Maximum allowed index of sample's last frame.
    Returns:
        list: List of sampled frame indices.
    """
    converted_len = int(clip_len * frame_sample_rate)
    end_idx = np.random.randint(converted_len, seg_len) if seg_len > converted_len else seg_len - 1
    start_idx = end_idx - converted_len
    start_idx = max(start_idx, 0)
    indices = np.linspace(start_idx, end_idx, num=clip_len)
    indices = np.clip(indices, start_idx, end_idx - 1).astype(np.int64)
    return indices

def save_feature_extractor(model, output_dir):
    """Save the model as a feature extractor (without classification head)."""
    os.makedirs(output_dir, exist_ok=True)
    
    # Save vision encoder with LoRA
    model.vision_encoder.save_pretrained(os.path.join(output_dir, "vision_encoder"))
    
    # Save image processor
    model.image_processor.save_pretrained(os.path.join(output_dir, "image_processor"))
    
    # Save configuration
    config = {
        "vision_encoder_id": model.config.vision_encoder_id,
        "num_frames": model.num_frames,
        "num_classes": model.num_classes,
        "num_views": model.num_views
    }
    
    with open(os.path.join(output_dir, "config.json"), 'w') as f:
        json.dump(config, f, indent=2)
    
    print(f"Feature extractor successfully saved to {output_dir}")

def load_feature_extractor(model_dir, device="auto"):
    """Load the model as a feature extractor."""
    # Load configuration
    with open(os.path.join(model_dir, "config.json"), 'r') as f:
        config = json.load(f)
    
    # Create model config
    model_config = VideoClassifierConfig(
        vision_encoder_id=config["vision_encoder_id"],
        num_frames=config["num_frames"],
        num_classes=config["num_classes"],
        num_views=config["num_views"]
    )
    
    # Initialize model
    model = VideoClassifier(model_config)
    
    # Load vision encoder with LoRA weights
    model.vision_encoder = PeftModel.from_pretrained(
        model.vision_encoder, 
        os.path.join(model_dir, "vision_encoder")
    )
    
    # Load image processor
    model.image_processor = AutoImageProcessor.from_pretrained(
        os.path.join(model_dir, "image_processor")
    )
    
    print(f"Feature extractor successfully loaded from {model_dir}")
    return model

def train(args):
    """Train the model."""
    # Determine maximum number of views
    global max_views
    max_views = max(len(args.camera_indices), 1)
    
    # Create datasets
    train_dataset = VideoDataset(
        args.train_annotation_path, 
        args.camera_indices, 
        args.video_root, 
        args.num_frames
    )
    
    eval_dataset = VideoDataset(
        args.test_annotation_path,
        args.camera_indices,
        args.video_root,
        args.num_frames
    ) if args.test_annotation_path else None
    
    # Create model
    config = VideoClassifierConfig(
        vision_encoder_id=VISION_ENCODER,
        num_frames=args.num_frames,
        num_classes=4,  # Fixed number of classes
        num_views=max_views
    )
    
    model = VideoClassifier(config)
    
    # Create the VideoProcessor 
    video_processor = VideoProcessor(model.image_processor)
    
    # Training arguments
    training_args = TrainingArguments(
        output_dir=f"{args.output_dir}/checkpoints",
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        lr_scheduler_type=args.lr_scheduler_type,
        weight_decay=args.weight_decay,
        warmup_ratio=args.warmup_ratio,
        fp16=True,
        logging_steps=args.logging_steps,
        save_strategy="epoch",
        eval_strategy="epoch" if eval_dataset else "no",
        load_best_model_at_end=True if eval_dataset else False,
        save_total_limit=2,
        remove_unused_columns=False,
        push_to_hub=args.push_to_hub,
        hub_model_id=args.hub_model_id if args.push_to_hub else None,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        dataloader_pin_memory=True,
        torch_empty_cache_steps=4,
        optim=args.optim,
    )
    
    # Create trainer
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        compute_metrics=compute_metrics,
        data_collator=partial(collate_fn, video_processor=video_processor)
    )
    
    # Train
    trainer.train()
    
    # Save model
    save_feature_extractor(model, args.output_dir)
    
    # Push to hub if requested
    if args.push_to_hub:
        model.push_to_hub(args.hub_model_id)
    
    return model

def inference(args, model=None):
    """Run inference on test dataset."""
    global max_views
    max_views = max(len(args.camera_indices), 1)
    
    # Load model if not provided
    if model is None:
        model = load_feature_extractor(args.model_path)
        model.to(DEVICE)
        model.eval()
    
    # Create test dataset
    test_dataset = VideoDataset(
        args.test_annotation_path,
        args.camera_indices,
        args.video_root,
        args.num_frames
    )
    
    # Create video processor
    video_processor = VideoProcessor(model.image_processor)
    
    # Create dataloader
    collate_partial = partial(collate_fn, video_processor=video_processor)
    test_loader = torch.utils.data.DataLoader(
        test_dataset,
        batch_size=args.batch_size,
        collate_fn=collate_partial
    )
    
    # Run inference
    all_preds = []
    all_labels = []
    
    with torch.no_grad():
        for batch in test_loader:
            pixel_values = batch["pixel_values"].to(DEVICE)
            labels = batch["labels"].to(DEVICE)
            
            outputs = model(pixel_values=pixel_values)
            logits = outputs["logits"]
            preds = torch.argmax(logits, dim=-1)
            
            all_preds.extend(preds.cpu().numpy())
            all_labels.extend(labels.cpu().numpy())
    
    # Compute accuracy
    accuracy = accuracy_score(all_labels, all_preds)
    print(f"Test accuracy: {accuracy:.4f}")
    
    return accuracy

def main():
    parser = argparse.ArgumentParser(description="Video Classification with TimesFormer and LoRA")
    parser.add_argument("--train_annotation_path", type=str, help="Path to the train dataset annotation file (JSONL format)")
    parser.add_argument("--test_annotation_path", type=str, help="Path to the test dataset annotation file (JSONL format)")
    parser.add_argument("--video_root", type=str, help="Path to the root directory containing video files")
    parser.add_argument("--camera_indices", nargs='+', type=int, default=[0], help="Indices of camera views to use")
    parser.add_argument("--num_frames", type=int, default=16, help="Number of frames to sample from each video")
    
    parser.add_argument("--epochs", type=int, default=10, help="Number of training epochs")
    parser.add_argument("--batch_size", type=int, default=4, help="Batch size per device during training")
    parser.add_argument("--learning_rate", type=float, default=5e-5, help="Learning rate for the optimizer")
    parser.add_argument("--lr_scheduler_type", type=str, default="cosine_with_restarts", help="Type of learning rate scheduler.")
    parser.add_argument("--weight_decay", type=float, default=0.01, help="Weight decay for the optimizer")
    parser.add_argument("--warmup_ratio", type=float, default=0.1, help="Warmup ratio for the learning rate scheduler")
    parser.add_argument("--logging_steps", type=int, default=10, help="Number of steps between logging")
    parser.add_argument("--gradient_accumulation_steps", type=int, default=4, help="Number of gradient accumulation steps.")
    parser.add_argument("--optim", type=str, default="adamw_torch", help="Optimizer to use.")
    
    parser.add_argument("--output_dir", type=str, default="./timesformer_classifier", help="Directory to save the model")
    parser.add_argument("--push_to_hub", action="store_true", help="Push model to Hugging Face Hub")
    parser.add_argument("--hub_model_id", type=str, help="Model ID for Hugging Face Hub")
    
    parser.add_argument("--do_train", action="store_true", help="Run training")
    parser.add_argument("--do_inference", action="store_true", help="Run inference")
    parser.add_argument("--model_path", type=str, help="Path to the model directory for inference")
    
    args = parser.parse_args()
    
    # Set global max_views
    global max_views
    max_views = max(len(args.camera_indices), 1)
    
    model = None
    
    if args.do_train:
        print("Starting training...")
        model = train(args)
    
    if args.do_inference:
        print("Starting inference...")
        inference(args, model)

if __name__ == "__main__":
    main()