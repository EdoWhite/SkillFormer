import json
import os

def remove_duplicates_from_jsonl(input_file, output_file):
    seen_first_paths = {}
    
    total_lines = 0
    unique_lines = 0
    
    with open(input_file, 'r') as f_in, open(output_file, 'w') as f_out:
        for line in f_in:
            total_lines += 1
            
            if not line.strip():
                continue
            
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                print(f"Errore nel decodificare la riga: {line}")
                continue
            
            if "video_paths" in item and isinstance(item["video_paths"], list) and len(item["video_paths"]) > 0:
                first_path = item["video_paths"][0]
                
                if first_path not in seen_first_paths:
                    seen_first_paths[first_path] = True
                    f_out.write(line)
                    unique_lines += 1
            else:
                f_out.write(line)
                unique_lines += 1
    
    duplicates = total_lines - unique_lines
    print(f"Processed rows: {total_lines}")
    print(f"Unique rows: {unique_lines}")
    print(f"Removed duplicates: {duplicates}")
    
    return unique_lines, duplicates

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python remove_duplicates.py input.jsonl [output.jsonl]")
        sys.exit(1)
    
    input_file = sys.argv[1]
    
    if len(sys.argv) >= 3:
        output_file = sys.argv[2]
    else:
        base_name = os.path.basename(input_file)
        output_file = "unique_" + base_name
    
    if not os.path.exists(input_file):
        print(f"Input file {input_file} not found.")
        sys.exit(1)
    
    print(f"Removing from {input_file}...")
    unique, duplicates = remove_duplicates_from_jsonl(input_file, output_file)
    print(f"File saved at {output_file}")