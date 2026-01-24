import re

def clean_file(path):
    with open(path, 'r') as f:
        lines = f.readlines()
    
    new_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Match "finally:" with optional whitespace and maybe a comment on same line
        if re.match(r"^\s*finally:\s*(#.*)?$", line):
            # Check next non-empty lines for content
            found_content = False
            for j in range(i + 1, min(i + 5, len(lines))):
                next_line = lines[j].strip()
                if next_line and not next_line.startswith("#"):
                    found_content = True
                    break
            
            if not found_content:
                # Add pass if empty finally
                indent = re.match(r"^(\s*)", line).group(1)
                new_lines.append(line)
                new_lines.append(f"{indent}    pass\n")
                i += 1
                # Skip the # await r.close() line if it follows
                while i < len(lines) and (not lines[i].strip() or lines[i].strip().startswith("# await r.close()")):
                    new_lines.append(lines[i]) # Keep comments but we added pass
                    i += 1
                continue
        
        new_lines.append(line)
        i += 1
        
    with open(path, 'w') as f:
        f.writelines(new_lines)

clean_file("web/backend/utils.py")
clean_file("web/backend/main.py")
print("Cleaned successfully.")
