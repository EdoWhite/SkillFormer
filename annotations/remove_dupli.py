import json
import os

def remove_duplicates_from_jsonl(input_file, output_file):
    """
    Rimuove le righe duplicate da un file JSONL.
    Le righe sono considerate duplicate quando il primo elemento del campo "video_paths" è uguale.
    
    Args:
        input_file (str): Percorso del file JSONL di input
        output_file (str): Percorso del file JSONL di output senza duplicati
    """
    # Dizionario per tenere traccia dei primi percorsi video già visti
    seen_first_paths = {}
    
    # Contatori per le statistiche
    total_lines = 0
    unique_lines = 0
    
    # Leggi il file di input e scrivi le righe uniche nel file di output
    with open(input_file, 'r') as f_in, open(output_file, 'w') as f_out:
        for line in f_in:
            total_lines += 1
            
            # Salta righe vuote
            if not line.strip():
                continue
            
            # Carica il JSON dalla riga
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                print(f"Errore nel decodificare la riga: {line}")
                continue
            
            # Estrai il primo percorso video
            if "video_paths" in item and isinstance(item["video_paths"], list) and len(item["video_paths"]) > 0:
                first_path = item["video_paths"][0]
                
                # Se questo è un nuovo percorso, aggiungilo al dizionario e scrivi la riga
                if first_path not in seen_first_paths:
                    seen_first_paths[first_path] = True
                    f_out.write(line)
                    unique_lines += 1
            else:
                # Se non c'è il campo video_paths o è malformato, scrivi comunque la riga
                f_out.write(line)
                unique_lines += 1
    
    # Stampa le statistiche
    duplicates = total_lines - unique_lines
    print(f"Totale righe processate: {total_lines}")
    print(f"Righe uniche: {unique_lines}")
    print(f"Duplicati rimossi: {duplicates}")
    
    return unique_lines, duplicates

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Utilizzo: python remove_duplicates.py input.jsonl [output.jsonl]")
        sys.exit(1)
    
    input_file = sys.argv[1]
    
    if len(sys.argv) >= 3:
        output_file = sys.argv[2]
    else:
        # Se non viene specificato un file di output, crea un nuovo file con prefisso "unique_"
        base_name = os.path.basename(input_file)
        output_file = "unique_" + base_name
    
    if not os.path.exists(input_file):
        print(f"File di input {input_file} non trovato.")
        sys.exit(1)
    
    print(f"Rimozione duplicati da {input_file}...")
    unique, duplicates = remove_duplicates_from_jsonl(input_file, output_file)
    print(f"File senza duplicati salvato in {output_file}")