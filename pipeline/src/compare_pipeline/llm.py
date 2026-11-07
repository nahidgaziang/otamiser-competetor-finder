import logging
import time
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel
from sqlalchemy import text

from compare_pipeline.config import settings
from compare_pipeline.db import get_pipeline_session
from compare_pipeline.models import LLMCall

logger = logging.getLogger("llm")

_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "models.yaml"

T = TypeVar("T", bound=BaseModel)


class SpendCapExceededError(Exception):
    """Raised when aggregate AI inference cost exceeds hard spend cap ($5.00 USD)."""


def load_model_config() -> dict[str, Any]:
    if not _CONFIG_PATH.exists():
        return {
            "default_model": "claude-haiku-5-5",
            "cap_usd": 5.00,
            "models": {
                "claude-haiku-5-5": {
                    "prompt_price_per_million": 1.00,
                    "completion_price_per_million": 5.00,
                }
            },
        }
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_current_spend_usd() -> float:
    """Queries app.llm_calls to calculate cumulative AI spend."""
    with get_pipeline_session() as session:
        val = session.execute(
            text("SELECT COALESCE(SUM(cost_usd), 0) FROM app.llm_calls;")
        ).scalar_one()
        return float(val)


def calculate_call_cost(
    model_name: str, prompt_tokens: int, completion_tokens: int
) -> float:
    cfg = load_model_config()
    model_cfg = cfg.get("models", {}).get(model_name, {})
    p_rate = model_cfg.get("prompt_price_per_million", 1.00)
    c_rate = model_cfg.get("completion_price_per_million", 5.00)

    prompt_cost = (prompt_tokens / 1_000_000.0) * p_rate
    completion_cost = (completion_tokens / 1_000_000.0) * c_rate
    return round(prompt_cost + completion_cost, 6)


class LLMClient:
    def __init__(self, model_name: str | None = None):
        cfg = load_model_config()
        self.config = cfg
        self.model_name = model_name or cfg.get("default_model", "claude-haiku-5-5")
        self.cap_usd = float(cfg.get("cap_usd", 5.00))
        self.api_key = settings.ANTHROPIC_API_KEY

    def check_spend_cap(self, estimated_cost: float = 0.05):
        current_spend = get_current_spend_usd()
        if current_spend + estimated_cost > self.cap_usd:
            raise SpendCapExceededError(
                f"Hard spend cap of ${self.cap_usd:.2f} USD exceeded. Current spend: ${current_spend:.4f} USD."
            )

    def generate_structured(
        self,
        prompt: str,
        response_model: type[T],
        system_prompt: str = "You are an expert hospitality and revenue management analyst.",
        job_id: uuid.UUID | None = None,
        stage: str = "generate",
    ) -> T:
        """
        Executes strict structured LLM generation with spend tracking and logging.
        If ANTHROPIC_API_KEY is not configured, provides a mock-structured response for testing.
        """
        # Token-count safety check before calling the model
        estimated_tokens = len(prompt) // 4
        max_prompt = self.config.get("max_prompt_tokens", 90000)
        if estimated_tokens > max_prompt:
            raise ValueError(
                f"Prompt exceeds max_prompt_tokens ({estimated_tokens} > {max_prompt})"
            )

        self.check_spend_cap()
        start_time = time.time()

        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY is not configured; cannot call LLM")

        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key)

        output_config = {
            "format": {
                "type": "json_schema",
                "schema": response_model.model_json_schema(),
            }
        }

        response = client.messages.create(
            model=self.model_name,
            max_tokens=16384,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
            output_config=output_config,
        )

        duration_ms = int((time.time() - start_time) * 1000)
        prompt_tokens = getattr(response.usage, "input_tokens", 0)
        completion_tokens = getattr(response.usage, "output_tokens", 0)
        cost = calculate_call_cost(self.model_name, prompt_tokens, completion_tokens)

        raw_text = "{}"
        if response.content:
            for block in response.content:
                if getattr(block, "type", None) == "text" or hasattr(block, "text"):
                    raw_text = block.text
                    break

        # Log call before model validation so spend cap is accurately tracked even on parse failure
        self._log_call(
            job_id=job_id,
            stage=stage,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost,
            duration_ms=duration_ms,
            prompt_preview=prompt[:200],
            response_preview=raw_text[:200],
        )

        return response_model.model_validate_json(raw_text)

    def _log_call(
        self,
        job_id: uuid.UUID | None,
        stage: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float,
        duration_ms: int,
        prompt_preview: str,
        response_preview: str,
    ):
        with get_pipeline_session() as session:
            call = LLMCall(
                job_id=job_id,
                stage=stage,
                model=self.model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=Decimal(str(cost_usd)),
                duration_ms=duration_ms,
                prompt_preview=prompt_preview,
                response_preview=response_preview,
            )
            session.add(call)
            session.commit()

    def _create_mock_instance(self, model_cls: type[T]) -> T:
        """Constructs a deterministic valid instance for unit testing and offline development."""
        from compare_pipeline.models_article import (
            ArticleDraft,
            DifferenceSection,
            FAQItem,
            FeatureCell,
            FeatureRow,
            SourcedParagraph,
            TableCategory,
            TextRun,
        )

        if model_cls is ArticleDraft:
            p1 = SourcedParagraph(
                runs=[
                    TextRun(
                        text="Short-term rental and hotel revenue management demands accurate daily algorithmic rate adjustments. Choosing the right pricing platform directly determines property occupancy and RevPAR execution across major distribution channels."
                    )
                ],
                fact_id="fact-ota-ranking",
            )
            p2 = SourcedParagraph(
                runs=[
                    TextRun(
                        text="This comparison analyzes core capabilities, algorithm methodologies, distribution integrations, and operational models between Otamiser and the competitor."
                    )
                ],
                fact_id="fact-done-for-you",
            )

            comp_p = SourcedParagraph(
                runs=[
                    TextRun(
                        text="The competitor provides specialized dynamic pricing software focused on automated rate suggestions based on historical market pacing and competitor calendar tracking."
                    )
                ],
                claim_id="claim-sample-1",
            )
            base_p = SourcedParagraph(
                runs=[
                    TextRun(
                        text="Otamiser provides an AI-native, done-for-you revenue management operation connecting algorithmic dynamic pricing directly with daily OTA search ranking positions across Airbnb, Booking.com, Vrbo, and Expedia."
                    )
                ],
                fact_id="fact-dynamic-pricing",
            )

            diff1 = DifferenceSection(
                title="Search Ranking Tracking as an Active Rate Signal",
                paragraphs=[
                    SourcedParagraph(
                        runs=[
                            TextRun(
                                text="Most pricing tools calibrate rates strictly against local market occupancy. Otamiser treats your actual search position on Booking.com and Airbnb as an active daily input that dictates rate strategy in real time."
                            )
                        ],
                        fact_id="fact-ota-ranking",
                    ),
                    SourcedParagraph(
                        runs=[
                            TextRun(
                                text="When search ranking drops, algorithmic pricing responds immediately to restore top-of-search visibility and capture booking velocity."
                            )
                        ],
                        fact_id="fact-auto-diagnosis",
                    ),
                ],
            )
            diff2 = DifferenceSection(
                title="Done-For-You Execution vs Software Subscription",
                paragraphs=[
                    SourcedParagraph(
                        runs=[
                            TextRun(
                                text="Software tools leave the setup, custom rule adjustments, and daily monitoring entirely to the host. Otamiser provides dedicated revenue managers paired with continuous automated algorithmic management."
                            )
                        ],
                        fact_id="fact-done-for-you",
                    ),
                    SourcedParagraph(
                        runs=[
                            TextRun(
                                text="This ensures continuous rate optimization without requiring hours of manual calendar maintenance each week."
                            )
                        ],
                        fact_id="fact-managed-deals",
                    ),
                ],
            )

            cat1 = TableCategory(
                category_name="Search & Ranking Visibility",
                rows=[
                    FeatureRow(
                        feature_name="Daily OTA search position tracking",
                        competitor_cell=FeatureCell(
                            state="no", text_content="Not listed"
                        ),
                        baseline_cell=FeatureCell(
                            state="yes",
                            fact_id="fact-ota-ranking",
                            text_content="Included",
                        ),
                    ),
                    FeatureRow(
                        feature_name="Ranking drop diagnosis and recovery",
                        competitor_cell=FeatureCell(
                            state="no", text_content="Not listed"
                        ),
                        baseline_cell=FeatureCell(
                            state="yes",
                            fact_id="fact-auto-diagnosis",
                            text_content="Automated",
                        ),
                    ),
                ],
            )
            cat2 = TableCategory(
                category_name="Dynamic Pricing & Algorithms",
                rows=[
                    FeatureRow(
                        feature_name="Real-time demand rate calibration",
                        competitor_cell=FeatureCell(
                            state="yes",
                            claim_id="claim-sample-1",
                            text_content="Supported",
                        ),
                        baseline_cell=FeatureCell(
                            state="yes",
                            fact_id="fact-dynamic-pricing",
                            text_content="Automated",
                        ),
                    ),
                    FeatureRow(
                        feature_name="Cross-channel rate synchronization",
                        competitor_cell=FeatureCell(
                            state="partial", text_content="Requires PMS"
                        ),
                        baseline_cell=FeatureCell(
                            state="yes",
                            fact_id="fact-ota-ranking",
                            text_content="Direct 2-way sync",
                        ),
                    ),
                ],
            )
            cat3 = TableCategory(
                category_name="Operational Model",
                rows=[
                    FeatureRow(
                        feature_name="Done-for-you revenue management team",
                        competitor_cell=FeatureCell(
                            state="no", text_content="Self-service tool"
                        ),
                        baseline_cell=FeatureCell(
                            state="yes",
                            fact_id="fact-done-for-you",
                            text_content="Full management",
                        ),
                    ),
                    FeatureRow(
                        feature_name="Booking.com Genius & Deals management",
                        competitor_cell=FeatureCell(
                            state="no", text_content="Not listed"
                        ),
                        baseline_cell=FeatureCell(
                            state="yes",
                            fact_id="fact-managed-deals",
                            text_content="Fully managed",
                        ),
                    ),
                ],
            )

            faqs = [
                FAQItem(
                    question="How does Otamiser differ from traditional pricing tools?",
                    answer=[
                        SourcedParagraph(
                            runs=[
                                TextRun(
                                    text="Otamiser connects daily search visibility position on OTAs directly to rate pricing algorithms, managing the complete execution rather than just offering software dashboards."
                                )
                            ],
                            fact_id="fact-ota-ranking",
                        )
                    ],
                ),
                FAQItem(
                    question="Does the competitor support multi-calendar syncing?",
                    answer=[
                        SourcedParagraph(
                            runs=[
                                TextRun(
                                    text="Yes, both platforms synchronize pricing across channels either through direct integrations or connected PMS systems."
                                )
                            ],
                            claim_id="claim-sample-1",
                        )
                    ],
                ),
                FAQItem(
                    question="Is there a setup fee or long-term contract?",
                    answer=[
                        SourcedParagraph(
                            runs=[
                                TextRun(
                                    text="Pricing models vary by provider with flexible monthly terms available depending on portfolio size and operational tier."
                                )
                            ],
                            fact_id="fact-done-for-you",
                        )
                    ],
                ),
                FAQItem(
                    question="Can I keep my current property management system (PMS)?",
                    answer=[
                        SourcedParagraph(
                            runs=[
                                TextRun(
                                    text="Yes, modern revenue platforms integrate seamlessly with leading PMS software including Guesty, Hostaway, and Hospitable."
                                )
                            ],
                            fact_id="fact-dynamic-pricing",
                        )
                    ],
                ),
            ]

            # Build ~1050 words prose text to satisfy gate minimum
            long_para = SourcedParagraph(
                runs=[
                    TextRun(
                        text="In the competitive short term rental and boutique hotel landscape, achieving sustainable profitability requires more than simply pushing fixed seasonal rates. Revenue management algorithms must evaluate continuous real-time market signals including pacing, local lead time compression, and neighborhood event demand. Furthermore, visibility on online travel agencies such as Booking.com and Airbnb follows algorithmic ranking criteria that favor listings with high booking conversion velocity and dynamic calendar responsiveness. By pairing daily search position metrics directly with automated dynamic adjustments, property managers protect their visibility during demand lulls while maximizing average daily rate during peak booking windows. This integrated methodology eliminates blind spots associated with standalone rate recommendations."
                    )
                ],
                fact_id="fact-ota-ranking",
            )
            long_para_2 = SourcedParagraph(
                runs=[
                    TextRun(
                        text="Modern hospitality operations must also navigate complex distribution requirements across multiple Online Travel Agencies. Listings on Airbnb require different calendar adjustment cadences compared to Booking.com, where traveler search habits differ across international and domestic cohorts. Rather than forcing property managers to constantly adjust manual minimum stay rules, automated revenue intelligence systems continuously simulate demand elasticity across every booking channel. This systematic approach ensures that rate increases capture maximum yield without causing sudden drops in search visibility or conversion rates."
                    )
                ],
                fact_id="fact-dynamic-pricing",
            )
            long_para_3 = SourcedParagraph(
                runs=[
                    TextRun(
                        text="Furthermore, effective revenue management involves active optimization of platform-specific merchandising programs. Programs such as Booking.com Genius, Preferred Partner badges, and mobile-only rates significantly impact visibility when deployed at the exact right moment in the booking window. Automated operations continuously monitor property conversion metrics and activate targeted discounts only when incremental revenue justifies the margin adjustment, preventing needless rate dilution during natural high-demand periods."
                    )
                ],
                fact_id="fact-managed-deals",
            )

            return ArticleDraft(
                title="Otamiser vs Competitor: 2026 Revenue Management Guide",
                meta_description="Detailed comparison between Otamiser and the competitor. Compare OTA ranking tracking, dynamic pricing, and managed revenue execution.",
                slug="otamiser-vs-sample-competitor",
                competitor_name="Sample Competitor",
                competitor_domain="samplecompetitor.com",
                intro=[p1, p2, long_para],
                competitor_overview=[comp_p, long_para, long_para_2],
                baseline_overview=[base_p, long_para, long_para_3],
                differences=[diff1, diff2],
                who_is_it_for=[long_para_2, long_para_3],
                pricing_analysis=[long_para, long_para_2],
                results_impact=[long_para_3],
                comparison_table=[cat1, cat2, cat3],
                faqs=faqs,
                cta_heading="Ready to automate your OTA revenue?",
                cta_description="See how Otamiser combines daily search ranking tracking with automated dynamic pricing to increase RevPAR.",
                cta_button_text="Schedule Free Demo",
                cta_button_url="https://www.otamiser.com/book-demo",
            )
        raise ValueError(f"No mock generator defined for {model_cls}")
