from langchain_core.messages import AIMessage
import streamlit as st
from graph import graph_runnable, MAX_TOKENS
from utility_func import TokenExceededException


async def invoke_graph(st_messages, st_placeholder, st_user_id):
    """
    Asynchronously processes a stream of events from the graph_runnable and updates the Streamlit interface.

    Args:
        st_messages (list): List of messages to be sent to the graph_runnable.
        st_placeholder (st.beta_container): Streamlit placeholder used to display updates and statuses.
        st_user_id (string): User ID to pass to the graph_runnable

    Returns:
        AIMessage: An AIMessage object containing the final aggregated text content from the events.
    """
    # Set up placeholders for displaying updates in the Streamlit app
    container = st_placeholder  # This container will hold the dynamic Streamlit UI components
    thoughts_placeholder = container.container()  # Container for displaying status messages
    token_placeholder = container.empty()  # Placeholder for displaying progressive token updates
    final_text = ""  # Will store the accumulated text from the model's response
    total_tokens_used = 0

    # Stream events from the graph_runnable asynchronously
    # config = {"configurable": {"user_id": st_user_id}}
    async for event in graph_runnable.astream_events({"messages": st_messages, "user_id": st_user_id}, version="v2"):

        # Get token count from events
        if "output" in event['data'] and "messages" in event['data']['output']:
            last_message = event["data"]["output"]["messages"][-1]
            if isinstance(last_message, AIMessage):
                total_tokens_used = max(total_tokens_used, last_message.usage_metadata["total_tokens"])
        elif "input" in event['data'] and event["data"]["input"] and "messages" in event["data"]["input"]:
            last_message = event["data"]["input"]["messages"][-1]
            if isinstance(last_message, AIMessage):
                total_tokens_used = max(total_tokens_used, last_message.usage_metadata["total_tokens"])

        # Stop the execution once the user exceeded the token limit
        if total_tokens_used > MAX_TOKENS:
            # final_text is passed as an argument to save AI's response in st.session_state.messages
            raise TokenExceededException("Token limit exceeded. Restart the conversation.", final_text)

        # Handle events
        kind = event["event"]  # Determine the type of event received

        if kind == "on_chat_model_stream":
            # The event corresponding to a stream of new content (tokens or chunks of text)
            addition = event["data"]["chunk"].content  # Extract the new content chunk
            final_text += addition  # Append the new content to the accumulated text
            if addition:
                token_placeholder.write(final_text)  # Update the st placeholder with the progressive response

        elif kind == "on_tool_start":
            # The event signals that a tool is about to be called
            with thoughts_placeholder:
                status_placeholder = st.empty()  # Placeholder to show the tool's status
                with status_placeholder.status("Calling Tool...", expanded=True) as s:
                    st.write("Called ", event['name'])  # Show which tool is being called
                    st.write("Tool input: ")
                    st.code(event['data'].get('input'))  # Display the input data sent to the tool
                    st.write("Tool output: ")
                    output_placeholder = st.empty()  # Placeholder for tool output that will be updated later
                    s.update(label="Completed Calling Tool!", expanded=False)  # Update the status once done

        elif kind == "on_tool_end":
            # The event signals the completion of a tool's execution
            with thoughts_placeholder:
                if 'output_placeholder' in locals():
                    try:
                        output_placeholder.code(event['data'].get('output').content)  # Display the tool's output
                    except AttributeError:
                        output_placeholder.code(event['data'].get('output'))
    print(total_tokens_used)
    # Return the final aggregated message after all events have been processed
    return final_text
