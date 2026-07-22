# 「수지(收支)」 — 부동산 개발 수지분석 리서치
# 표준 개발 워크플로: make setup → collect → analyze → build → test
# venv 가 있으면 그 파이썬을, 없으면 시스템 python3 를 사용한다.

PY ?= $(shell [ -x venv/bin/python ] && echo venv/bin/python || echo python3)
PORT ?= 8765
COLLECTORS = ecos rone rone_sub rone_commercial kosis presale sbiz rtms

.DEFAULT_GOAL := help
.PHONY: help setup collect analyze forecast manifest build test serve refresh all clean

help:            ## 타깃 목록
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[1m%-10s\033[0m %s\n", $$1, $$2}'

setup:           ## 가상환경 생성 + 의존성 설치
	$(PY) -m venv venv
	venv/bin/pip install -U pip
	venv/bin/pip install -r requirements.txt
	@echo "→ config.json 에 API 키를 채우세요 (.env.example 참조)"

collect:         ## 공공 API 원천 수집 → data/*.json (config.json 키 필요)
	@for s in $(COLLECTORS); do echo "==> collect: $$s"; $(PY) src/collect/$$s.py || exit 1; done

analyze:         ## 수집 데이터 → 분석 산출물 out/*.json (market·cases·eda)
	$(PY) src/analysis/market.py
	$(PY) -m src.analysis.cases
	$(PY) src/analysis/eda.py

forecast:        ## 6모델 롤링 백테스트 → out/forecast.json (torch 필요·수십 분)
	$(PY) -m src.forecast.build

manifest:        ## 데이터 원장 DATA_MANIFEST.json 생성 (관측월·수집일·건수)
	$(PY) src/build/manifest.py

build:           ## 사이트 조립 → web/ (매니페스트·빌드 스탬프 포함)
	$(PY) src/build/assemble.py

test:            ## 단위테스트 176 (수기검산·골든·Python↔JS 패리티)
	$(PY) -m pytest tests/ -q

serve:           ## 로컬 서버 http://localhost:$(PORT) (봇필터·noindex)
	$(PY) serve.py $(PORT)

refresh:         ## 전체 파이프라인 (수집→분석→빌드→검증, 배포 제외)
	$(PY) src/pipeline/refresh.py --no-deploy

all: analyze build test   ## 분석·빌드·테스트 일괄 (수집 생략)

clean:           ## 빌드 산출물 제거 (web/·web.tmp·out/site.html)
	rm -rf web web.tmp out/site.html
