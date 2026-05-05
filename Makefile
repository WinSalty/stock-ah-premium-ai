.PHONY: bootstrap check init-db backend frontend stop stop-backend stop-frontend restart restart-backend restart-frontend

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

stop:
	./scripts/stop.sh

stop-backend:
	./scripts/stop-backend.sh

stop-frontend:
	./scripts/stop-frontend.sh

restart:
	./scripts/restart.sh

restart-backend:
	./scripts/restart-backend.sh

restart-frontend:
	./scripts/restart-frontend.sh
