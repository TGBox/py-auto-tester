# ROUTINE_NAME: Demo Login & Terminplaner
# ROUTINE_DESC: Logged sich im AL Dashboard ein und öffnet Terminplaner.

def execute(page, vars):
    base_url = vars.get('BASE_URL', 'https://dr.data-al.cloud/aldashboard/login?returnUrl=%2Fhome')
    username = vars.get('USERNAME', 'admin@demo.de')
    password = vars.get('PASSWORD', 'danitest')

    page.goto(base_url)
    page.get_by_role('textbox', name='E-Mail').click()
    page.get_by_role('textbox', name='E-Mail').fill(username)
    page.get_by_role('textbox', name='E-Mail').press('Tab')
    page.get_by_role('textbox', name='Passwort').fill(password)
    page.get_by_role('textbox', name='Passwort').press('Tab')
    page.get_by_role('button').filter(has_text='check').click()
    page.get_by_role('link', name='Terminplaner').click()
