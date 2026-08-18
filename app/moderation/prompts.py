from __future__ import annotations

import json
from typing import Any

PROMPT_VERSION = "sentinelai-telegram-v1"

CLASSIFIER_SYSTEM_PROMPT = (
    "You are an AI moderation classifier for Telegram group chats. Your job is to "
    "detect spam, scam, phishing, porn-bait clickbait, malicious Telegram bot links, "
    "suspicious invite links, and compromised-account propagation messages. You must "
    "distinguish malicious or unwanted promotion from legitimate conversation. Consider "
    "the message text, links, sender context, group settings, known examples, and "
    "rule-based signals. Return strict JSON only. Do not include chain-of-thought. "
    "Give short reason phrases only."
)


OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "label",
        "confidence",
        "risk_reasons",
        "safe_reasons",
        "detected_lure_type",
        "recommended_action",
        "needs_training_review",
    ],
    "properties": {
        "label": {"type": "string", "enum": ["spam", "suspicious", "not_spam"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "risk_reasons": {"type": "array", "items": {"type": "string"}},
        "safe_reasons": {"type": "array", "items": {"type": "string"}},
        "detected_lure_type": {
            "type": ["string", "null"],
            "enum": [
                "porn_bait",
                "phishing",
                "crypto_scam",
                "fake_giveaway",
                "malware",
                "impersonation",
                "spam_channel_promo",
                "suspicious_bot_link",
                "suspicious_invite_link",
                "unknown",
                None,
            ],
        },
        "recommended_action": {
            "type": "string",
            "enum": ["delete", "delete_and_ban", "ask_admin", "allow"],
        },
        "needs_training_review": {"type": "boolean"},
    },
}


def build_classifier_messages(payload: dict[str, Any]) -> list[dict[str, str]]:
    instructions = {
        "task": "Classify this Telegram group message for anti-spam moderation.",
        "be_sensitive_to": [
            "free porn",
            "leaked video",
            "18+ video",
            "watch before deleted",
            "watch before takedown",
            "link expires in 60s",
            "tap to watch",
            "tap to play",
            "watch now",
            "see more",
            "full video",
            "view full scene",
            "watch uncut",
            "unlock video",
            "hidden cam",
            "private tape",
            "banned from OnlyFans",
            "adult clickbait captions paired with t.me bot startapp links",
            "join private channel",
            "click bot to verify",
            "claim reward",
            "free Telegram Premium",
            "crypto airdrop",
            "connect wallet",
            "login to continue",
            "suspicious t.me bot start links",
            "forwarded Telegram stories from adult-bait channels",
            "suspicious invite links",
            "repeated link-only posts",
            "compromised-user style messages",
        ],
        "avoid_false_positives_for": [
            "normal memes",
            "security discussions about spam",
            "legitimate group rules",
            "admins warning about scams",
            "users discussing Telegram spam",
            "legitimate YouTube, Twitter, GitHub, or news links",
            "normal adult-topic discussion without clickbait links",
            "short harmless replies like 'Www' or 'This is good' when the current message has no spam link or bait",
            "forwarded news or educational content",
        ],
        "output_schema": OUTPUT_SCHEMA,
        "message": payload,
    }
    return [
        {"role": "system", "content": CLASSIFIER_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(instructions, ensure_ascii=False)},
    ]
