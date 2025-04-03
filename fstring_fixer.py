#!/usr/bin/env python
import re

def fix_fstrings():
    with open('accounts/views.py', 'r') as f:
        content = f.read()
    
    # Fix f-strings with escaped quotes
    # Replace \' with " inside f-strings
    pattern = r'f"([^"]*)\\\\'([^"]*)\\\\'([^"]*)"'
    replacement = r'f"\1"\2"\3"'
    content = re.sub(pattern, replacement, content)
    
    # Another pattern: f"{\'Some text\' if condition else \'Other text\'}"
    pattern = r"f\"\{\\\'([^\\']*)\\\'([^}]*)\\\\'([^}]*)\}\""
    replacement = r'f"{\1\2\3}"'
    content = re.sub(pattern, replacement, content)
    
    # Write the fixed content back to the file
    with open('accounts/views.py', 'w') as f:
        f.write(content)
    
    print('Successfully fixed f-string issues in views.py')

if __name__ == '__main__':
    fix_fstrings() 