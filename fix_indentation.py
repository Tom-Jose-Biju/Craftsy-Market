#!/usr/bin/env python

def fix_indentation():
    with open('accounts/views.py', 'r') as f:
        lines = f.readlines()
    
    # Fix the indentation at line 372
    lines[371] = '                return redirect(\'admin_add_category\')\n'
    
    with open('accounts/views.py', 'w') as f:
        f.writelines(lines)
    
    print('Successfully fixed the indentation issue.')

if __name__ == '__main__':
    fix_indentation() 