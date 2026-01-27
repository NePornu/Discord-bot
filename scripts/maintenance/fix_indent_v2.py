import re

def fix(path):
    with open(path, 'r') as f:
        content = f.read()
    
    
    content = re.sub(r'#\s*finally:', 'finally:', content)
    
    
    
    lines = content.splitlines()
    new_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if re.match(r'^\s*finally:\s*$', line):
            new_lines.append(line)
            
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            
            if j < len(lines):
                next_content = lines[j].strip()
                if not next_content or next_content.startswith("#") or next_content == "pass":
                    
                    
                    indent = re.match(r'^(\s*)', line).group(1)
                    new_lines.append(f"{indent}    pass")
                    
                    while i + 1 < len(lines) and (not lines[i+1].strip() or lines[i+1].strip().startswith("pass") or lines[i+1].strip().startswith("#")):
                        i += 1
                        if lines[i].strip() == "pass": continue 
                        new_lines.append(lines[i])
                else:
                    
                    pass
        else:
            new_lines.append(line)
        i += 1
        
    with open(path, 'w') as f:
        f.write("\n".join(new_lines) + "\n")

fix("web/backend/utils.py")
fix("web/backend/main.py")
print("Fixed.")
