from crypto_signals.domain.schemas import Position, Signal
from polyfactory.factories.pydantic_factory import ModelFactory


class SignalFactory(ModelFactory[Signal]):
    __model__ = Signal


class PositionFactory(ModelFactory[Position]):
    __model__ = Position
