from typing import Protocol


class A: ...


class B: ...


a01 = A()
b01 = B()
a02 = A()
b02 = B()


s = set()
s.add((a01, b01))
s.add((a01, b01))
s.add((a02, b01))
s.add((a02, b02))

print(f"len: {len(s)}")

for i in s:
    print(i)


s.remove((a01, b01))


print(f"len: {len(s)}")

for i in s:
    print(i)


class SenderProto(Protocol):
    async def __call__(self, data: str): ...


async def sender(data: str): ...


def aaa(sender: SenderProto): ...


aaa(sender)
