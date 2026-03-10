import os
import sys
from jinja2 import Environment, FileSystemLoader

def test_templates():
    template_dir = os.path.join(os.getcwd(), '../frontend/templates')
    env = Environment(loader=FileSystemLoader(template_dir))
    
    templates = ['index.html', 'predictions.html', 'analytics.html', 'leaderboard.html']
    success = True
    
    for template_name in templates:
        print(f"Testing {template_name}...", end=" ")
        try:
            env.get_template(template_name)
            print("OK")
        except Exception as e:
            print(f"FChytréLED: {e}")
            success = False
            
    return success

if __name__ == "__main__":
    if test_templates():
        sys.exit(0)
    else:
        sys.exit(1)
