# Integrations

memsearch is a plain Python library -- it works with any framework. This page shows ready-made patterns for **[LangChain](https://www.langchain.com/)**, **[LangGraph](https://langchain-ai.github.io/langgraph/)**, **[LlamaIndex](https://www.llamaindex.ai/)**, and **[CrewAI](https://www.crewai.com/)**.

!!! note "Prerequisites"
    Each integration requires its own packages:

    ```bash
    $ pip install langchain langchain-openai    # LangChain examples
    $ pip install langgraph                      # LangGraph agent example
    $ pip install llama-index-core              # LlamaIndex example
    $ pip install crewai                         # CrewAI example
    ```

---

## LangChain

### As a Retriever

Wrap `MemSearch` in a LangChain [`BaseRetriever`](https://python.langchain.com/docs/how_to/custom_retriever/) so it plugs into any LangChain chain or agent.

```python
import asyncio
from pydantic import ConfigDict
from memsearch import MemSearch
from langchain_core.retrievers import BaseRetriever
from langchain_core.documents import Document
from langchain_core.callbacks import CallbackManagerForRetrieverRun


class MemSearchRetriever(BaseRetriever):
    """LangChain retriever backed by memsearch."""

    mem: MemSearch
    top_k: int = 5
    model_config = ConfigDict(arbitrary_types_allowed=True)

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        results = asyncio.run(self.mem.search(query, top_k=self.top_k))
        return [
            Document(
                page_content=r["content"],
                metadata={
                    "source": r["source"],
                    "heading": r["heading"],
                    "score": r["score"],
                },
            )
            for r in results
        ]
```

Use it like any other LangChain retriever:

```python
mem = MemSearch(paths=["./memory/"])
asyncio.run(mem.index())

retriever = MemSearchRetriever(mem=mem, top_k=3)
docs = retriever.invoke("Redis caching")
# [Document(page_content="We chose Redis for caching...", metadata={...}), ...]
```

### RAG Chain

Combine the retriever with an LLM using [LCEL](https://python.langchain.com/docs/concepts/lcel/) (LangChain Expression Language) for a simple retrieval-augmented generation pipeline:

```python
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser

llm = ChatOpenAI(model="gpt-4o-mini")
retriever = MemSearchRetriever(mem=mem, top_k=3)


def format_docs(docs: list[Document]) -> str:
    return "\n\n".join(doc.page_content for doc in docs)


prompt = ChatPromptTemplate.from_template(
    "Use the following context to answer the question.\n\n"
    "Context:\n{context}\n\n"
    "Question: {question}\n"
    "Answer:"
)

rag_chain = (
    {"context": retriever | format_docs, "question": RunnablePassthrough()}
    | prompt
    | llm
    | StrOutputParser()
)

answer = rag_chain.invoke("what caching solution are we using?")
print(answer)
```

---

## LangGraph

### As a Tool (ReAct Agent)

Wrap memsearch as a [tool](https://python.langchain.com/docs/concepts/tools/) and let a [LangGraph ReAct agent](https://langchain-ai.github.io/langgraph/agents/) decide when to search:

```python
import asyncio
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from memsearch import MemSearch

mem = MemSearch(paths=["./memory/"])
asyncio.run(mem.index())


@tool
def search_memory(query: str) -> str:
    """Search the team's knowledge base for relevant information."""
    results = asyncio.run(mem.search(query, top_k=3))
    if not results:
        return "No relevant memories found."
    return "\n\n".join(
        f"[{r['source']}] {r['heading']}: {r['content'][:300]}"
        for r in results
    )


llm = ChatOpenAI(model="gpt-4o-mini")
agent = create_react_agent(llm, [search_memory])

result = agent.invoke(
    {"messages": [("user", "Who is our frontend lead and what did they work on?")]}
)

# The agent automatically calls search_memory when it needs information
for msg in result["messages"]:
    role = msg.__class__.__name__
    if hasattr(msg, "tool_calls") and msg.tool_calls:
        print(f"{role}: [called search_memory]")
    elif hasattr(msg, "content") and msg.content:
        print(f"{role}: {msg.content[:200]}")
```

The agent will autonomously decide when to call `search_memory` based on the user's question -- no manual retrieval logic needed.

---

## LlamaIndex

### As a Retriever

Implement a LlamaIndex [`BaseRetriever`](https://docs.llamaindex.ai/en/stable/api_reference/retrievers/) that delegates to memsearch. Results are returned as `NodeWithScore` objects that work with any LlamaIndex query engine or pipeline.

```python
import asyncio
from typing import List
from memsearch import MemSearch
from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import NodeWithScore, TextNode, QueryBundle


class MemSearchRetriever(BaseRetriever):
    """LlamaIndex retriever backed by memsearch."""

    def __init__(self, mem: MemSearch, top_k: int = 5) -> None:
        self._mem = mem
        self._top_k = top_k
        super().__init__()

    def _retrieve(self, query_bundle: QueryBundle) -> List[NodeWithScore]:
        results = asyncio.run(
            self._mem.search(query_bundle.query_str, top_k=self._top_k)
        )
        return [
            NodeWithScore(
                node=TextNode(
                    text=r["content"],
                    metadata={"source": r["source"], "heading": r["heading"]},
                ),
                score=r["score"],
            )
            for r in results
        ]
```

Use it like any other LlamaIndex retriever:

```python
mem = MemSearch(paths=["./memory/"])
asyncio.run(mem.index())

retriever = MemSearchRetriever(mem=mem, top_k=3)
nodes = retriever.retrieve("Redis caching")
for n in nodes:
    print(f"[{n.score:.4f}] {n.node.metadata['source']} — {n.node.text[:100]}")
```

Plug it into a `RetrieverQueryEngine` for end-to-end RAG (requires an LLM provider like `llama-index-llms-openai`):

```python
from llama_index.core.query_engine import RetrieverQueryEngine

query_engine = RetrieverQueryEngine.from_args(retriever)
response = query_engine.query("what caching solution are we using?")
print(response)
```

---

## CrewAI

### As a Tool (Multi-Agent Crew)

Register memsearch as a [CrewAI tool](https://docs.crewai.com/en/concepts/tools) so any agent in the crew can search the knowledge base:

```python
import asyncio
from memsearch import MemSearch
from crewai import Agent, Task, Crew
from crewai.tools import tool

mem = MemSearch(paths=["./memory/"])
asyncio.run(mem.index())


@tool("search_memory")
def search_memory(query: str) -> str:
    """Search the team's knowledge base for relevant information."""
    results = asyncio.run(mem.search(query, top_k=3))
    if not results:
        return "No relevant memories found."
    return "\n\n".join(
        f"[{r['source']}] {r['heading']}: {r['content'][:300]}"
        for r in results
    )


researcher = Agent(
    role="Knowledge Base Researcher",
    goal="Find relevant information from the team's knowledge base",
    backstory="You are a researcher who searches the team's knowledge base to answer questions.",
    tools=[search_memory],
)

research_task = Task(
    description="Who is the frontend lead and what did they work on recently?",
    expected_output="A short summary mentioning the frontend lead's name and recent work.",
    agent=researcher,
)

crew = Crew(agents=[researcher], tasks=[research_task])
result = crew.kickoff()
print(result)
```

The agent will automatically call `search_memory` to look up the answer before responding.
