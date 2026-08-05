import unittest

from ingestion.metadata import build_vector_id, enrich_document_metadata, parse_key_value_content
from rag.generation.prompt_builder import build_messages, build_retrieval_query, summarize_sources
from rag.memory.conversation import ConversationMemory, ConversationStore
from rag.retriever.context_builder import ContextBuilder
from rag.retriever.query_processor import QueryProcessor


class MetadataTests(unittest.TestCase):
    def test_parse_key_value_content(self):
        content = "tcode: ME21N\ntitle: Create Purchase Order\nmodule: MM"
        fields = parse_key_value_content(content)
        self.assertEqual(fields["tcode"], "ME21N")
        self.assertEqual(fields["module"], "MM")

    def test_enrich_document_metadata(self):
        class Doc:
            page_content = "tcode: ME21N\ntitle: Create Purchase Order\nmodule: MM"
            metadata = {"filename": "tcodes.csv", "row": 3}

        doc = Doc()
        enrich_document_metadata(doc)
        self.assertEqual(doc.metadata["document_type"], "tcode")
        self.assertEqual(doc.metadata["module"], "MM")
        self.assertEqual(doc.metadata["title"], "Create Purchase Order")

    def test_build_vector_id_is_deterministic(self):
        class Doc:
            metadata = {"filename": "tcodes.csv", "row": 3}

        doc = Doc()
        first = build_vector_id(doc, 10)
        second = build_vector_id(doc, 10)
        self.assertEqual(first, second)


class QueryProcessorTests(unittest.TestCase):
    def setUp(self):
        self.processor = QueryProcessor()

    def test_clean_query(self):
        self.assertEqual(self.processor.clean_query("  hello   world  "), "hello world")
        self.assertEqual(self.processor.clean_query(None), "")

    def test_normalize_filters(self):
        filters = self.processor.normalize_filters({"Module": "MM", "Document Type": "tcode"})
        self.assertEqual(filters, {"module": "MM", "document_type": "tcode"})

    def test_to_pinecone_filter_single(self):
        pinecone_filter = self.processor.to_pinecone_filter({"module": "MM"})
        self.assertEqual(pinecone_filter, {"module": {"$eq": "MM"}})

    def test_to_pinecone_filter_multiple(self):
        pinecone_filter = self.processor.to_pinecone_filter({"module": "MM", "document_type": "tcode"})
        self.assertIn("$and", pinecone_filter)


class ContextBuilderTests(unittest.TestCase):
    def test_build_uses_normalized_fields(self):
        builder = ContextBuilder()
        context = builder.build(
            [
                {
                    "score": 0.91,
                    "source_file": "tcodes.csv",
                    "document_type": "tcode",
                    "module": "MM",
                    "title": "Create Purchase Order",
                    "content": "tcode: ME21N",
                    "metadata": {"document_type": "csv"},
                }
            ]
        )
        self.assertIn("Module: MM", context)
        self.assertIn("Title: Create Purchase Order", context)
        self.assertIn("Document Type: tcode", context)


class MemoryTests(unittest.TestCase):
    def test_conversation_trim(self):
        memory = ConversationMemory(max_turns=2)
        memory.add_user_message("one")
        memory.add_assistant_message("two")
        memory.add_user_message("three")
        memory.add_assistant_message("four")
        memory.add_user_message("five")
        memory.add_assistant_message("six")
        self.assertEqual(len(memory.get_messages()), 4)
        self.assertEqual(memory.get_messages()[0]["content"], "three")

    def test_session_store_reuses_session(self):
        store = ConversationStore()
        first = store.get_or_create("abc", max_turns=5)
        second = store.get_or_create("abc", max_turns=5)
        self.assertIs(first, second)


class PromptBuilderTests(unittest.TestCase):
    def test_build_messages_includes_history(self):
        messages = build_messages(
            query="What tcode should I use?",
            context="tcode: ME21N",
            history=[{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello"}],
        )
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1]["content"], "Hi")
        self.assertEqual(messages[-1]["role"], "user")

    def test_summarize_sources_deduplicates(self):
        results = [
            {"id": "1", "source_file": "a.csv", "title": "A", "content": "x", "score": 0.9},
            {"id": "1", "source_file": "a.csv", "title": "A", "content": "x", "score": 0.9},
        ]
        sources = summarize_sources(results)
        self.assertEqual(len(sources), 1)

    def test_build_retrieval_query_includes_history(self):
        retrieval_query = build_retrieval_query(
            "What tcode did you mention?",
            [
                {"role": "user", "content": "How do I create a PO?"},
                {"role": "assistant", "content": "Use ME21N"},
            ],
        )
        self.assertIn("Follow-up question", retrieval_query)
        self.assertIn("ME21N", retrieval_query)


if __name__ == "__main__":
    unittest.main()
