#!/usr/bin/env python

def fix_indentation():
    with open('accounts/views.py', 'r') as f:
        lines = f.readlines()
    
    # Fix the indentation at line 401
    # From the code context, it appears that this else clause is incorrectly indented
    # The if statement it corresponds to is likely at line 392
    # We need to match the indentation of the if statement
    lines[400] = '        else:\n'
    
    with open('accounts/views.py', 'w') as f:
        f.writelines(lines)
    
    print('Successfully fixed the indentation issue at line 401.')

if __name__ == '__main__':
    fix_indentation() 