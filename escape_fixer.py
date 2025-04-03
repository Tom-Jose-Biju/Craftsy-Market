#!/usr/bin/env python

def fix_escape_chars():
    with open('accounts/views.py', 'r') as f:
        content = f.read()
    
    # Replace all escaped single quotes in redirect calls with regular single quotes
    content = content.replace("redirect(\\'", "redirect('")
    content = content.replace("\\')", "')")
    
    # Write the fixed content back to the file
    with open('accounts/views.py', 'w') as f:
        f.write(content)
    
    print('Successfully fixed escape character issues in views.py')

if __name__ == '__main__':
    fix_escape_chars() 