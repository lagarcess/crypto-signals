from polyfactory.factories.pydantic_factory import ModelFactory
from crypto_signals.domain.schemas import Signal, Position

class SignalFactory(ModelFactory[Signal]):
    __model__ = Signal

class PositionFactory(ModelFactory[Position]):
    __model__ = Position
