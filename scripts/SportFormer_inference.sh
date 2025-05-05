#!/bin/bash
#SBATCH --ntasks=4
#SBATCH --mem=80G
#SBATCH --partition=gpu-pre
#SBATCH --account=pro-est
#SBATCH --output=./out/SportFormer-inference-ego-%j.out
#SBATCH --error=./out/SportFormer-inference-ego-%j.err
#SBATCH --gres=gpu:a100-sxm4-80gb
#SBATCH --time=5-00:00:00

module load python/3.9.15-aocc-3.2.0-linux-ubuntu22.04-zen2
module load cuda/12.4
source /home/clusterusers/edbianchi/proficiency/bin/activate

cd /data/users/edbianchi/SportFormer

python model.py \
    --test_annotation_path /data/users/edbianchi/ProfiVLM/annotations/debug_annotation_val.jsonl \
    --video_root /data/users/edbianchi/EgoExoData \
    --camera_indices 0 \
    --num_frames 32 \
    --output_dir ./trained_models/SportFormer-EgoV3 \
    --model_path ./trained_models/SportFormer-EgoV3 \
    --batch_size 4 \
    --do_inference
