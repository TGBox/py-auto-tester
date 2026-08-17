# ROUTINE_NAME: Wiki Close Test
# ROUTINE_DESC: Test

def execute(page, vars):
    page.goto('https://www.wikipedia.org')
    page.get_by_role('link', name='Deutsch').click()
