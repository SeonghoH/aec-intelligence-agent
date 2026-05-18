"""End-to-end LLM smoke test.

Constructs a synthetic high-score item with a tiny full-text file, then
runs the real Gemini summarizer once. Use this to verify your API key
and prompt setup without waiting for the right paper to appear in the
daily pipeline.

Cost: one Gemini call (~$0 on the free tier, otherwise ~$0.05).

Usage:
    python3 scripts/test_llm_smoke.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aec_intel_agent.full_text import STATUS_FULL_TEXT_EXTRACTED
from aec_intel_agent.llm_summarizer import (
    _provider_api_key,
    get_max_chars,
    get_model,
    get_provider,
    is_enabled,
    summarize_item,
)
from aec_intel_agent.models import StandardItem


# A short, realistic-looking AEC paper extract (deliberately short to
# keep the call cheap). Replace with a real .txt from
# data/full_text/<slug>.txt if you want a higher-fidelity test.
SAMPLE_TEXT = """\
Title: BIM-based digital twin framework for structural monitoring of steel buildings

Abstract:
This paper proposes a Building Information Modeling (BIM) integrated
digital twin framework for real-time structural health monitoring of
multi-story steel buildings. The framework combines IFC-based BIM
models, IoT sensor data streams, and a finite element surrogate model
to provide deformation and stress estimates during construction and
operation. A case study on a 12-story steel frame demonstrates that
the proposed pipeline can detect bolt loosening events with 92%
precision and reduces inspection effort by 35% compared to baseline
periodic checks.

Methodology:
We instrument the test structure with 24 strain gauges and 8 MEMS
accelerometers. Sensor data are streamed into a digital twin built
from the project's IFC4 model. A reduced-order finite element surrogate
trained on baseline measurements provides nominal response. Anomaly
detection uses a one-class SVM on the residual between measured and
predicted strain. The full pipeline is implemented in Python on
commodity hardware.

Results:
Over a 90-day deployment we detected 11 bolt-loosening events; 10 were
confirmed manually (precision 0.92, recall 0.83). Inspection time was
reduced from 12 to 8 person-hours per week. Limitations include
sensitivity to sensor drift over multi-month deployments.

Conclusion:
The framework demonstrates that BIM-anchored digital twins can provide
practical structural monitoring for steel construction at lower cost
than dedicated SHM systems. Future work includes extending to LCA-based
embodied carbon tracking through the construction phase.
"""


def main() -> int:
    if not is_enabled():
        print("❌ LLM_ENABLED is not 'true' in .env.")
        return 1

    provider = get_provider()
    api_key = _provider_api_key(provider)
    if not api_key:
        print(f"❌ API key for provider {provider!r} is not set.")
        return 1

    model = get_model()
    max_chars = get_max_chars()

    # Write the sample text to a temp file so summarize_item() reads it
    # exactly the same way the real pipeline would.
    with tempfile.TemporaryDirectory() as tmpdir:
        text_path = Path(tmpdir) / "smoke.txt"
        text_path.write_text(SAMPLE_TEXT, encoding="utf-8")

        item = StandardItem(
            title="BIM-based digital twin framework for structural monitoring of steel buildings",
            source="arxiv",
            url="http://arxiv.org/abs/0000.00000",
            item_type="preprint",
            score=95,
            topics=["bim", "digital_twin", "structural_steel"],
            full_text_status=STATUS_FULL_TEXT_EXTRACTED,
            full_text_path=str(text_path),
            metadata={"source_type": "preprint"},
        )

        print(f"→ Calling {provider} / {model} (max_chars={max_chars})…")
        summary = summarize_item(
            item, provider=provider, model=model, api_key=api_key,
            max_chars=max_chars,
        )

    print("\n--- LLM Summary (Korean) ---")
    print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2))
    print("\n--- End ---")

    if summary.summary_status == "Summarized":
        print("\n✅ LLM 호출 성공. 노션 11개 필드에 들어갈 한국어 결과입니다.")
        return 0
    print("\n❌ LLM 호출 실패. 위의 status를 확인하세요.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
