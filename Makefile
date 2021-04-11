CF_HOME ?= $(HOME)
CF      ?= cf

# deploys can respond to STG env variable if they support
# feature branches or alternate production builds
PRD_BRANCH    ?= master
PRD_STAGE     ?= stg
STG_PREFIX    ?= feat-
CIRCLE_BRANCH ?=
BRANCH        ?= $(CIRCLE_BRANCH)
FEATURE        = $(BRANCH:$(STG_PREFIX)%=%)

# set prod stage if we're on prod branch
ifeq ($(BRANCH), $(PRD_BRANCH))
	export STG ?= $(PRD_STAGE)
endif

# export stg variable only if we are on a feature branch
ifneq ($(BRANCH), $(FEATURE))
	export STG ?= f-$(FEATURE)
endif

all: install

cf-login:
	@$(CF) login\
		-a "${CF_API_STAGING}"\
		-u "${CF_USERNAME}"\
		-p "${CF_PASSWORD_STAGING}"\
		-o "dta_notify"\
		-s "${CF_SPACE}"

cf-login-prod:
	@$(CF) login\
		-a "${CF_API_PROD}"\
		-u "${CF_USERNAME}"\
		-p "${CF_PASSWORD_PROD}"\
		-o "dta"\
		-s "${CF_SPACE}"

DIRS        = api admin utils docs
TARGETS     = install install-dev build check-vulnerabilities clean deploy deploy-dev test
API_TARGETS = run-celery-worker run-celery-worker-default run-celery-worker-priority run-celery-worker-sender run-celery-worker-callbacks run-celery-worker-retrys run-celery-worker-internal run-celery-beat deploy-celery-worker-default deploy-celery-worker-priority deploy-celery-worker-sender deploy-celery-worker-callbacks deploy-celery-worker-retrys deploy-celery-worker-internal deploy-dev-celery-worker deploy-dev-celery-worker-default deploy-dev-celery-worker-priority deploy-dev-celery-worker-sender deploy-dev-celery-worker-callbacks deploy-dev-celery-worker-retrys deploy-dev-celery-worker-internal deploy-celery-beat deploy-dev-celery-beat
CI_TARGETS  = create-service-psql create-service-redis setup-ses-callback loadtesting-run
ANY_TARGETS = $(TARGETS) $(API_TARGETS) $(CI_TARGETS)

$(ANY_TARGETS:%=\%.%):
	$(MAKE) -C $* $(@:$*.%=%)

$(TARGETS):
	$(MAKE) $(DIRS:%=%.$@)

$(API_TARGETS):
	$(MAKE) api.$@

$(CI_TARGETS):
	$(MAKE) ci.$@

.PHONY: cf-login cf-login-prod $(ANY_TARGETS)
