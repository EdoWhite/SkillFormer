#!/bin/bash
#SBATCH --ntasks=4
#SBATCH --mem=80G
#SBATCH --partition=gpu-pre
#SBATCH --account=pro-est
#SBATCH --output=./out/SportFormer-ego-v4-%j.out
#SBATCH --error=./out/SportFormer-ego-v4-%j.err
#SBATCH --gres=gpu:a100-sxm4-80gb
#SBATCH --time=5-00:00:00

module load python/3.9.15-aocc-3.2.0-linux-ubuntu22.04-zen2
module load cuda/12.4
source /home/clusterusers/edbianchi/proficiency/bin/activate

cd /data/users/edbianchi/SportFormer

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
