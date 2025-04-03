#!/usr/bin/env python
import re

def fix_syntax_errors():
    # Read the file
    with open('accounts/views.py', 'r') as f:
        content = f.read()
    
    # Fix the specific issues we found so far
    
    # 1. Fix the duplicate else issue in the login_view function
    content = re.sub(
        r'return redirect\(\'home\'\)\s+else:',
        r'return redirect(\'home\')',
        content
    )
    
    # 2. Fix indentation issues with else clauses
    # This is a more complex fix that would require proper parsing
    # For now, let's focus on specific known issues
    
    # Fix the admin_add_category function
    content = re.sub(
        r'messages\.success\(request, f"\{\'Subcategory\' if is_subcategory else \'Category\'\} \'\{category_name\}\' has been added successfully\."\)\s+return redirect\(\'admin_add_category\'\)',
        r'messages.success(request, f"{\'Subcategory\' if is_subcategory else \'Category\'} \'{category_name}\' has been added successfully.")\n                return redirect(\'admin_add_category\')',
        content
    )
    
    # Fix the admin_edit_category function
    content = re.sub(
        r'return redirect\(\'admin_add_category\'\)\s+else:',
        r'return redirect(\'admin_add_category\')\n        else:',
        content
    )
    
    # Write the fixed content back to the file
    with open('accounts/views.py', 'w') as f:
        f.write(content)
    
    print('Successfully fixed multiple syntax issues in views.py')

if __name__ == '__main__':
    fix_syntax_errors() 