import json
import argparse
from pathlib import Path

"""
This script processes two JSON files: one containing proficiency data (proficiency_demonstrator) and another containing expert commentary (expert_commentary).
It extracts relevant information from both files and combines them into a single output file in JSONL format.
"""

def load_json(path):
    with open(path, "r") as f:
        return json.load(f)

def main(proficiency_path, commentary_path, output_path):
    proficiency_data = load_json(proficiency_path)
    commentary_data = load_json(commentary_path)

    # Create lookup dict
    proficiency_lookup = {
        entry["take_uid"]: {
            "video_paths": list(entry["video_paths"].values()),
            "proficiency_score": entry["proficiency_score"]
        }
        for entry in proficiency_data["annotations"]
    }

    results = []
    for take_uid, commentary_list in commentary_data["annotations"].items():
        if take_uid not in proficiency_lookup:
            continue
        video_paths = proficiency_lookup[take_uid]["video_paths"]
        proficiency_score = proficiency_lookup[take_uid]["proficiency_score"]

        for commentary in commentary_list:
            texts = [d["text"].strip() for d in commentary.get("commentary_data", []) if isinstance(d.get("text"), str)]
            if not texts:
                continue
            analysis = " ".join(texts)
            results.append({
                "video_paths": video_paths,
                "analysis": analysis,
                "proficiency_level": proficiency_score
            })

    with open(output_path, "w") as f:
        for item in results:
            f.write(json.dumps(item) + "\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--proficiency", required=True, help="Path to proficiency_demonstrator JSON file")
    parser.add_argument("--commentary", required=True, help="Path to expert_commentary JSON file")
    parser.add_argument("--output", required=True, help="Output JSONL file path")
    args = parser.parse_args()

    main(args.proficiency, args.commentary, args.output)