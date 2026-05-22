"""
Broker Abstraction Layer
========================
Import broker-agnostic types from here.

Switch brokers by setting BROKER= in .env.paper / .env.live (default: tradier).
Requires only that one-line change — no code edits needed.

    from trading.broker import (
        BrokerInterface, DataFeedInterface,
        OrderResult, QuoteResult, PositionResult, BarResult,
        TradierBroker, TradierDataFeed, TradierBarPoller,
    )

    # Alpaca — requires: pip install alpaca-py
    from trading.broker.alpaca import AlpacaBroker, AlpacaDataFeed, AlpacaBarStream
"""

from trading.broker.base import (
    BrokerInterface,
    DataFeedInterface,
    OrderResult,
    QuoteResult,
    PositionResult,
    BarResult,
)
from trading.broker.tradier import (
    TradierBroker,
    TradierDataFeed,
    TradierBarPoller,
)

# AlpacaBroker etc. are accessible at trading.broker.alpaca
# but NOT imported here by default (alpaca-py may not be installed).

__all__ = [
    # Interfaces
    'BrokerInterface',
    'DataFeedInterface',
    # Data classes
    'OrderResult',
    'QuoteResult',
    'PositionResult',
    'BarResult',
    # Tradier (active)
    'TradierBroker',
    'TradierDataFeed',
    'TradierBarPoller',
]
