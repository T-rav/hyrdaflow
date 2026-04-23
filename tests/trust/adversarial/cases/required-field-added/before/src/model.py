from pydantic import BaseModel


class Issue(BaseModel):
    number: int
    title: str
