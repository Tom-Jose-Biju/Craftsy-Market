#!/usr/bin/env python

def fix_fstrings():
    with open('accounts/views.py', 'r') as f:
        content = f.read()
    
    # Find and replace the specific problematic f-string
    problematic_string = "f\"{\\\'Subcategory\\\' if is_subcategory else \\\'Category\\\'} \\\'{category_name}\\\' has been added successfully.\""
    fixed_string = "f\"{'Subcategory' if is_subcategory else 'Category'} '{category_name}' has been added successfully.\""
    
    content = content.replace(problematic_string, fixed_string)
    
    # Write the fixed content back to the file
    with open('accounts/views.py', 'w') as f:
        f.write(content)
    
    print('Successfully fixed specific f-string issue in views.py')

if __name__ == '__main__':
    fix_fstrings() 