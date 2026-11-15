import asyncio
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt
class S(TypedDict, total=False):
    x: int
    approved: bool
def gate(s):
    d = interrupt({'ask': 'approve?'})
    return {'approved': d.get('approved', False)}
g=StateGraph(S); g.add_node('gate',gate); g.add_edge(START,'gate'); g.add_edge('gate',END)
app=g.compile(checkpointer=MemorySaver())
async def main():
    cfg={'configurable':{'thread_id':'t3'}}
    await app.ainvoke({'x':0}, cfg)
    st=await app.aget_state(cfg)
    print('next', st.next)
    print('tasks', st.tasks)
    print('interrupts', [t.interrupts for t in st.tasks])
asyncio.run(main())
