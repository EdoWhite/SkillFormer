import json
import os

# Carica il file splits.json
with open('/data/users/edbianchi/SkillFormer/annotations/splits.json', 'r') as f:
    splits_data = json.load(f)
    take_uid_to_split = splits_data['take_uid_to_split']

# Carica i file train.json e val.json
with open('/data/users/edbianchi/SkillFormer/annotations/proficiency_demonstrator_train.json', 'r') as f:
    train_data = json.load(f)

with open('/data/users/edbianchi/SkillFormer/annotations/proficiency_demonstrator_val.json', 'r') as f:
    val_data = json.load(f)

# Combina tutti i campioni da train e val in un dizionario per accesso rapido
all_samples_dict = {}
for sample in train_data['annotations'] + val_data['annotations']:
    all_samples_dict[sample['take_uid']] = sample

# Prepara liste per catalogare i campioni per split
train_samples = []
val_samples = []
test_samples = []

# Itera su ogni take_uid nel file splits.json
for take_uid, split in take_uid_to_split.items():
    # Cerca questo take_uid nel dizionario combinato
    if take_uid in all_samples_dict:
        sample = all_samples_dict[take_uid]
        
        # Crea una nuova struttura nel formato richiesto
        new_sample = {
            "video_paths": [
                sample["video_paths"]["ego"],
                sample["video_paths"]["exo1"],
                sample["video_paths"]["exo2"],
                sample["video_paths"]["exo3"],
                sample["video_paths"]["exo4"]
            ],
            "proficiency_level": sample.get("proficiency_score", "")  # Rinomina proficiency_score in proficiency_level
        }
        
        # Aggiungi il campione formattato alla lista corretta
        if split == 'train':
            train_samples.append(new_sample)
        elif split == 'val':
            val_samples.append(new_sample)
        elif split == 'test':
            test_samples.append(new_sample)
    else:
        print(f"Warning: take_uid {take_uid} non trovato nei file train.json o val.json")

# Funzione per scrivere i campioni in formato JSONL
def write_jsonl(samples, file_path):
    with open(file_path, 'w') as f:
        for sample in samples:
            # Scrivi il campione come una riga JSON
            f.write(json.dumps(sample) + '\n')

# Scrivi i file JSONL
write_jsonl(train_samples, 'train.jsonl')
write_jsonl(val_samples, 'val.jsonl')
write_jsonl(test_samples, 'test.jsonl')

print(f"Split completato:")
print(f"  Train: {len(train_samples)} campioni")
print(f"  Val: {len(val_samples)} campioni")
print(f"  Test: {len(test_samples)} campioni")