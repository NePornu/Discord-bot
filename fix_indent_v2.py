import re

def fix(path):
    with open(path, 'r') as f:
        content = f.read()
    
    # 1. Uncomment any "# finally:" or "#     finally:"
    content = re.sub(r'#\s*finally:', 'finally:', content)
    
    # 2. Match finally: and ensure next line is pass or something similar
    # This is tricky with regex. Let's do line by line.
    lines = content.splitlines()
    new_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if re.match(r'^\s*finally:\s*$', line):
            new_lines.append(line)
            # Peek at next non-empty line
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            
            if j < len(lines):
                next_content = lines[j].strip()
                if not next_content or next_content.startswith("#") or next_content == "pass":
                    # It's effectively empty or has pass already
                    # We ensure there is at least one pass
                    indent = re.match(r'^(\s*)', line).group(1)
                    new_lines.append(f"{indent}    pass")
                    # Consume any following comments that were intended for finally block
                    while i + 1 < len(lines) and (not lines[i+1].strip() or lines[i+1].strip().startswith("pass") or lines[i+1].strip().startswith("#")):
                        i += 1
                        if lines[i].strip() == "pass": continue # skip existing pass to avoid double
                        new_lines.append(lines[i])
                else:
                    # Next line has real content, finally is not empty.
                    pass
        else:
            new_lines.append(line)
        i += 1
        
    with open(path, 'w') as f:
        f.write("\n".join(new_lines) + "\n")

fix("web/backend/utils.py")
fix("web/backend/main.py")
print("Fixed.")
