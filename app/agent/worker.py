def main() -> None:
    """Boot the outbound-call worker process.

    Implemented once a voice-infra vendor (Bland / Retell / Vapi — see
    CLAUDE.md's Stack table) is picked after latency/IVR-navigation/cost
    evaluation. The adapter implements `engine.providers.base
    .VoicePlatformProvider` — engine/call_loop.py already depends only on
    that interface, so wiring in the real vendor is a new provider module,
    not a rewrite of the engine.
    """
    raise NotImplementedError(
        "voice-platform adapter pending vendor choice (Bland/Retell/Vapi); "
        "implement engine.providers.base.VoicePlatformProvider, see "
        "engine.providers.mock.MockVoicePlatformProvider for the shape"
    )


if __name__ == "__main__":
    main()
