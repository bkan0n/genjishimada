"""Bot unit tests (handler bodies + bot config decode).

Bot unit tests live under apps/api/tests/ because the bot has no dedicated pytest
config; handlers are exercised by invoking their bodies directly with mocked
``self.bot.api``, a mocked resolved channel, and fabricated event structs.
"""
