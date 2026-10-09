L app v1 -- Shared Neyvia SDK app
S app.current=app.state()
A app.connect() -- Read provider status through Neyvia's shared owner session
G: app.state().connected == true
