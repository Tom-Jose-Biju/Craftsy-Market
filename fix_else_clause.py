#!/usr/bin/env python

def fix_else_clause():
    with open('accounts/views.py', 'r') as f:
        lines = f.readlines()
    
    # The issue is around line 400 with a duplicate else clause
    # Looking at the code, it seems the structure should be:
    # if request.method == 'POST':
    #     if category_name:  # Line ~388
    #         ... code ...
    #     else:  # Line ~400 - This is the problematic one
    #         ... code ...
    # So we need to fix the indentation and structure
    
    # First, let's fix line 396-398 which seems to be an 'else' clause that's 
    # not indented properly and should be part of the 'if parent_id:' block
    lines[395] = '                else:\n'
    lines[396] = '                    category.parent = None\n'
    
    # Then remove the save() and success message from inside this else block
    # as they should be outside the if/else for parent_id handling
    lines[397] = '                category.save()\n'
    lines[398] = '                messages.success(request, f"Category \'{category.name}\' has been updated successfully.")\n'
    lines[399] = '                return redirect(\'admin_add_category\')\n'
    
    # Now fix the outer else clause (line 400)
    lines[400] = '        else:\n'
    
    with open('accounts/views.py', 'w') as f:
        f.writelines(lines)
    
    print('Successfully fixed else clause structure in admin_edit_category function')

if __name__ == '__main__':
    fix_else_clause() 