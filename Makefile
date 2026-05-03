.PHONY: bootstrap check init-db backend frontend

bootstrap:
	./scripts/bootstrap.sh

check:
	./scripts/check.sh

init-db:
	./scripts/init-db.sh

backend:
	./scripts/start-backend.sh

frontend:
	./scripts/start-frontend.sh
