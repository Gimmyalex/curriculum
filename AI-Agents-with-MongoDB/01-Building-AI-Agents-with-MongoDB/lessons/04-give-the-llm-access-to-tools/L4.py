import key_param
from pymongo import MongoClient
from langchain.agents import tool
from typing import List
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
import voyageai

def init_mongodb():
    """
    Initialize MongoDB client and collections.

    Returns:
        tuple: MongoDB client, vector search collection, full documents collection.
    """
    mongodb_client = MongoClient(key_param.mongodb_uri)
    
    DB_NAME = "ai_agents"
    
    vs_collection = mongodb_client[DB_NAME]["chunked_docs"]
    
    full_collection = mongodb_client[DB_NAME]["full_docs"]
    
    return mongodb_client, vs_collection, full_collection

    
def generate_embedding(text: str) -> List[float]:
    """
    Generate embedding for a piece of text.

    Args:
        text (str): The text to embed.
        embedding_model (voyage-3-lite): The embedding model.

    Returns:
        List[float]: The embedding of the text.
    """

    embedding_model = voyageai.Client(api_key=key_param.voyage_api_key)

    embedding = embedding_model.embed(text, model="voyage-3-lite", input_type="query").embeddings[0]
    
    return embedding


@tool 
def get_information_for_question_answering(user_query: str) -> str:
    """
    Retrieve relevant documents for a user query using vector search.

    Args:
        user_query (str): The user's query.

    Returns:
        str: The retrieved documents as a string.
    """

    query_embedding = generate_embedding(user_query)

    vs_collection = init_mongodb()[1]
    
    pipeline = [
        {
            # Use vector search to find similar documents
            "$vectorSearch": {
                "index": "vector_index",  # Name of the vector index
                "path": "embedding",       # Field containing the embeddings
                "queryVector": query_embedding,  # The query embedding to compare against
                "numCandidates": 150,      # Consider 150 candidates (wider search)
                "limit": 5,                # Return only top 5 matches
            }
        },
        {
            # Project only the fields we need
            "$project": {
                "_id": 0,                  # Exclude document ID
                "body": 1,                 # Include the document body
                "score": {"$meta": "vectorSearchScore"},  # Include the similarity score
            }
        },
    ]
    
    results = vs_collection.aggregate(pipeline)
    
    context = "\n\n".join([doc.get("body") for doc in results])
    
    return context

@tool  # Decorator marks this function as a tool the agent can use
def get_page_content_for_summarization(user_query: str) -> str:
    """
    Retrieve the content of a documentation page for summarization.

    Args:
        user_query (str): The user's query (title of the documentation page).

    Returns:
        str: The content of the documentation page.
    """
    full_collection = init_mongodb()[2]

    query = {"title": user_query}
    
    projection = {"_id": 0, "body": 1}
    
    document = full_collection.find_one(query, projection)
    
    if document:
        return document["body"]
    else:
        return "Document not found"


def main():
    """
    Main function to initialize and execute the graph.
    """
    
    mongodb_client, vs_collection, full_collection = init_mongodb()
    
    tools = [
        get_information_for_question_answering,
        get_page_content_for_summarization
    ]
    
    llm = ChatOpenAI(openai_api_key=key_param.openai_api_key, temperature=0, model="gpt-4o")
    
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "You are a helpful AI assistant."
                " You are provided with tools to answer questions and summarize technical documentation related to MongoDB."
                " Think step-by-step and use these tools to get the information required to answer the user query."
                " Do not re-run tools unless absolutely necessary."
                " If you are not able to get enough information using the tools, reply with I DON'T KNOW."
                " You have access to the following tools: {tool_names}."
            ),
            MessagesPlaceholder(variable_name="messages"),
        ]
    )
    
    prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
    
    bind_tools = llm.bind_tools(tools)
    
    llm_with_tools = prompt | bind_tools
    
    tool_call_check = llm_with_tools.invoke(["What are some best practices for data backups in MongoDB?"]).tool_calls
    print("Tool call check:")
    print(tool_call_check)
main()