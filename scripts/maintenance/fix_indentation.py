import re

def clean_file(path):
    with open(path, 'r') as f:
        lines = f.readlines()
    
    new_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        
        if re.match(r"^\s*finally:\s*(#.*)?$", line):
            
            found_content = False
            for j in range(i + 1, min(i + 5, len(lines))):
                next_line = lines[j].strip()
                if next_line and not next_line.startswith("#"):
                    found_content = True
                    break
            
            if not found_content:
                
                indent = re.match(r"^(\s*)", line).group(1)
                new_lines.append(line)
                new_lines.append(f"{indent}    pass\n")
                i += 1
                
                while i < len(lines) and (not lines[i].strip() or lines[i].strip().startswith("# await r.close()")):
                    new_lines.append(lines[i]) 
                    i += 1
                continue
        
        new_lines.append(line)
        i += 1
        
    with open(path, 'w') as f:
        f.writelines(new_lines)

clean_file("web/backend/utils.py")
clean_file("web/backend/main.py")
print("Cleaned successfully.")
