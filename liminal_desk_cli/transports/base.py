"""Transport-neutral completion contract and legacy Paho compatibility."""
from typing import Protocol


class Receipt(Protocol):
    def is_complete(self) -> bool:
        """True after the transport's stated completion point, or raise on error."""
        ...


def send_complete(receipt):
    if receipt is None:
        return True
    if hasattr(receipt, 'is_complete'):
        return receipt.is_complete()
    # Direct Broker users and the pre-existing fake publishers return Paho-style receipts.
    return receipt.is_published()


class MqttReceipt:
    def __init__(self, info):
        self.info = info

    def is_complete(self):
        return self.info.is_published()
