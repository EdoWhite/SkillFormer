# 🎯 SkillFormer: Unified Multi-View Video Understanding for Proficiency Estimation

**SkillFormer** is a lightweight yet powerful model designed for estimating skill proficiency from multi-view video recordings. Built upon the TimeSformer backbone and enhanced with a novel Attentive Projector module, it provides robust video understanding in real-world, multi-camera scenarios.

---

## 🔍 Highlights

- 🧠 **TimeSformer Backbone Fine-Tuned with LoRA**  
  Efficient low-rank adaptation (LoRA) allows fast, low-resource fine-tuning while retaining the benefits of large pretrained video transformers.

- 🧲 **Attentive Projector for Unified Multi-View Fusion**  
  A custom fusion module that integrates view-specific video features using:
  - Multi-Head Cross-Attention 🧩
  - Learnable Gating Mechanisms 🚪
  - Adaptive Calibration for Dynamic View Weighting 🎛️

---

## 🔧 Fine-Tuning Data

The model is fine-tuned on the [EgoExo4D](https://ego-exo4d-data.org) dataset, specifically on the "Proficiency Estimation" benchmark. This benchmark includes expert commentary paired with a proficiency label. The fine-tuning process trains the model to generate a natural language analysis of proficiency and produce a final proficiency label.

---

## 📁 Project Structure

- `model.py`: Defines `SkillFormere`
- `annotation/prepare_annotation.py`: Prepares data annotations in `.jsonl` format

---

## 🚀 Usage

### 1. Download Data and Prepare annotations
First get access to the dataset and install the required download utilities, following the [official documentation](https://docs.ego-exo4d-data.org).
Second, download the required set of data using the following command:

```bash
egoexo -o ./EgoExoData --benchmarks proficiency_demonstrator --parts downscaled_takes/448 expert_commentary annotations -y
```

Finbally, run the following command to prepare the annotations for training:

```bash
python prepare_annotation.py \
  --video_dir path/to/videos \
  --metadata path/to/raw_annotations.json \
  --output path/to/annotations.jsonl
```

### 2. Train the Model
```bash
python model.py \
    --do_train \
    --train_annotation_path /data/users/edbianchi/ProfiVLM/annotations/annotation_train.jsonl \
    --val_annotation_path /data/users/edbianchi/ProfiVLM/annotations/annotation_val.jsonl \
    --test_annotation_path /data/users/edbianchi/ProfiVLM/annotations/annotation_test.jsonl \
    --video_root /data/users/edbianchi/EgoExoData \
    --camera_indices 0 \
    --num_frames 64 \
    --epochs 4 \
    --output_dir ./trained_models/SportFormer-EgoV4 \
    --batch_size 4 \
    --gradient_accumulation_steps 4 \
    --lora_r 32 \
    --lora_alpha 64 \
    --lora_dropout 0.1 \
    --projector_hidden_dim 1536 \
    --projector_num_heads 16 \
    --learning_rate 5e-5 \
    --lr_scheduler_type cosine \
    --weight_decay 0.01 \
    --warmup_ratio 0.10 \
    --optim adamw_torch \
    --logging_steps 50 \
    --do_inference
```

> You can resume the training of an experiment by adding the ```--resume_from_checkpoint``` argument. The last chekcpoint of the specified ```--run_name``` will be loaded.

### 3. Inference
Run inference using the following command.

```bash
python model.py \
    --test_annotation_path /data/users/edbianchi/ProfiVLM/annotations/debug_annotation_val.jsonl \
    --video_root /data/users/edbianchi/EgoExoData \
    --camera_indices 0 \
    --num_frames 32 \
    --output_dir ./trained_models/SportFormer-EgoV3 \
    --model_path ./trained_models/SportFormer-EgoV3 \
    --batch_size 4 \
    --do_inference
```

> **Note**: Ensure that the `--camera_indices` and `--num_frames` values match the configuration used during model training to avoid inconsistencies in input processing.

---

## 🧪 Citation (Coming Soon)

If you use SkillFormer in your research or projects, please consider citing the upcoming paper.

---

## 📬 Contact

For questions or collaborations, open an issue or contact us at [edoardobianchi98@gmail.com].

---

💡 *SkillFormer is designed with research in mind. Contributions are welcome!*