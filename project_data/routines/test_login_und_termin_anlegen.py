# ROUTINE_NAME: Test Login und Termin anlegen
# ROUTINE_DESC: Aufgenommen von https://dr.data-al.cloud

def execute(page, vars):
    """Automatisch aufgenommene Routine."""
    page.goto("https://dr.data-al.cloud/aldashboard/login?returnUrl=%2Fhome")
    page.get_by_role("textbox", name="E-Mail").click()
    page.get_by_role("textbox", name="E-Mail").fill("admin@demo.de")
    page.get_by_role("textbox", name="E-Mail").press("Tab")
    page.get_by_role("textbox", name="Passwort").fill("danitest")
    page.get_by_role("button").filter(has_text="check").click()
    page.get_by_role("link", name="Terminplaner").click()
    page.get_by_role("combobox", name="Suche Patient (Name oder ID)").click()
    page.get_by_role("combobox", name="Suche Patient (Name oder ID)").fill("mustermann")
    page.get_by_text("Mustermann, Max").click()
    page.locator(".mbsc-flex-1-1 > div:nth-child(25)").first.dblclick()
    page.locator("div:nth-child(3) > .mbsc-flex-1-1 > div:nth-child(25)").first.dblclick()
    page.get_by_text("Mustermann Max").nth(1).click()
    page.get_by_role("button", name="Abbruch").click()
    page.get_by_role("button", name="Toggle sidenav").click()
    page.get_by_role("link", name="Logout Administrator").click()
