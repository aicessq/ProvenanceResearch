"""phase1 initial schema

Revision ID: 0001_phase1_initial
Revises:
Create Date: 2026-07-01 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0001_phase1_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("doc_type", sa.String(length=64), nullable=False),
        sa.Column("source_filename", sa.String(length=512), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("current_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'active'")),
        sa.Column("security_domain", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("idx_documents_doc_type", "documents", ["doc_type"], unique=False)
    op.create_index("idx_documents_status", "documents", ["status"], unique=False)
    op.create_index("idx_documents_created_at", "documents", [sa.text("created_at DESC")], unique=False)
    op.create_index("idx_documents_current_version_id", "documents", ["current_version_id"], unique=False)
    op.create_index("idx_documents_security_domain_gin", "documents", ["security_domain"], unique=False, postgresql_using="gin")
    op.create_index("idx_documents_tags_gin", "documents", ["tags"], unique=False, postgresql_using="gin")

    op.create_table(
        "query_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_query", sa.Text(), nullable=False),
        sa.Column("rewritten_query", sa.Text(), nullable=True),
        sa.Column("intent", sa.String(length=64), nullable=True),
        sa.Column("safety_action", sa.String(length=32), nullable=True),
        sa.Column("risk_type", sa.String(length=64), nullable=True),
        sa.Column("filters", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("retrieved_chunk_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("reranked_chunk_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("answer_status", sa.String(length=32), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("model_name", sa.String(length=128), nullable=True),
        sa.Column("feedback_score", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("idx_query_logs_created_at", "query_logs", [sa.text("created_at DESC")], unique=False)
    op.create_index("idx_query_logs_intent", "query_logs", ["intent"], unique=False)
    op.create_index("idx_query_logs_safety_action", "query_logs", ["safety_action"], unique=False)
    op.create_index("idx_query_logs_risk_type", "query_logs", ["risk_type"], unique=False)
    op.create_index("idx_query_logs_filters_gin", "query_logs", ["filters"], unique=False, postgresql_using="gin")

    op.create_table(
        "eval_datasets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_path", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'active'")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("name", name="uq_eval_datasets_name"),
    )
    op.create_index("idx_eval_datasets_status", "eval_datasets", ["status"], unique=False)
    op.create_index("idx_eval_datasets_created_at", "eval_datasets", [sa.text("created_at DESC")], unique=False)

    op.create_table(
        "document_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("file_hash", sa.String(length=128), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("version_status", sa.String(length=32), nullable=False, server_default=sa.text("'active'")),
        sa.Column("publish_date", sa.Date(), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("expire_date", sa.Date(), nullable=True),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("document_id", "version_no", name="uq_document_versions_document_id_version_no"),
    )
    op.create_index("idx_document_versions_document_id", "document_versions", ["document_id"], unique=False)
    op.create_index("idx_document_versions_version_status", "document_versions", ["version_status"], unique=False)
    op.create_index("idx_document_versions_effective_date", "document_versions", ["effective_date"], unique=False)
    op.create_index("idx_document_versions_publish_date", "document_versions", ["publish_date"], unique=False)
    op.create_index("idx_document_versions_file_hash", "document_versions", ["file_hash"], unique=False)

    op.create_foreign_key(
        "fk_documents_current_version_id_document_versions",
        "documents",
        "document_versions",
        ["current_version_id"],
        ["id"],
    )

    op.create_table(
        "feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("query_log_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("query_logs.id"), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("score >= 1 AND score <= 5", name="ck_feedback_score_range"),
    )
    op.create_index("idx_feedback_query_log_id", "feedback", ["query_log_id"], unique=False)
    op.create_index("idx_feedback_score", "feedback", ["score"], unique=False)

    op.create_table(
        "eval_dataset_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("eval_datasets.id"), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("expected_doc_type", sa.String(length=64), nullable=True),
        sa.Column("expected_keywords", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("expected_chunk_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("expected_refusal", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("idx_eval_dataset_items_dataset_id", "eval_dataset_items", ["dataset_id"], unique=False)
    op.create_index("idx_eval_dataset_items_expected_doc_type", "eval_dataset_items", ["expected_doc_type"], unique=False)
    op.create_index("idx_eval_dataset_items_expected_keywords_gin", "eval_dataset_items", ["expected_keywords"], unique=False, postgresql_using="gin")

    op.create_table(
        "eval_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("eval_datasets.id"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("completed_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("recall_at_k", sa.Numeric(10, 4), nullable=True),
        sa.Column("mrr", sa.Numeric(10, 4), nullable=True),
        sa.Column("citation_accuracy", sa.Numeric(10, 4), nullable=True),
        sa.Column("answer_groundedness", sa.Numeric(10, 4), nullable=True),
        sa.Column("refusal_accuracy", sa.Numeric(10, 4), nullable=True),
        sa.Column("average_latency_ms", sa.Numeric(10, 2), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index("idx_eval_runs_dataset_id", "eval_runs", ["dataset_id"], unique=False)
    op.create_index("idx_eval_runs_status", "eval_runs", ["status"], unique=False)
    op.create_index("idx_eval_runs_created_at", "eval_runs", [sa.text("created_at DESC")], unique=False)

    op.create_table(
        "chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("document_versions.id"), nullable=False),
        sa.Column("parent_chunk_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chunks.id"), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_type", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("chunk_hash", sa.String(length=128), nullable=False),
        sa.Column("doc_type", sa.String(length=64), nullable=False),
        sa.Column("doc_title", sa.String(length=512), nullable=False),
        sa.Column("chapter", sa.String(length=512), nullable=True),
        sa.Column("section", sa.String(length=512), nullable=True),
        sa.Column("article_no", sa.String(length=128), nullable=True),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("security_domain", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("keywords", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("search_tsv", postgresql.TSVECTOR(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("version_id", "chunk_index", name="uq_chunks_version_id_chunk_index"),
    )
    op.create_index("idx_chunks_document_id", "chunks", ["document_id"], unique=False)
    op.create_index("idx_chunks_version_id", "chunks", ["version_id"], unique=False)
    op.create_index("idx_chunks_doc_type", "chunks", ["doc_type"], unique=False)
    op.create_index("idx_chunks_chunk_type", "chunks", ["chunk_type"], unique=False)
    op.create_index("idx_chunks_is_active", "chunks", ["is_active"], unique=False)
    op.create_index("idx_chunks_chunk_hash", "chunks", ["chunk_hash"], unique=False)
    op.create_index("idx_chunks_parent_chunk_id", "chunks", ["parent_chunk_id"], unique=False)
    op.create_index("idx_chunks_article_no", "chunks", ["article_no"], unique=False)
    op.create_index("idx_chunks_page_start", "chunks", ["page_start"], unique=False)
    op.create_index("idx_chunks_page_end", "chunks", ["page_end"], unique=False)
    op.create_index("idx_chunks_metadata_gin", "chunks", ["metadata"], unique=False, postgresql_using="gin")
    op.create_index("idx_chunks_security_domain_gin", "chunks", ["security_domain"], unique=False, postgresql_using="gin")
    op.create_index("idx_chunks_keywords_gin", "chunks", ["keywords"], unique=False, postgresql_using="gin")
    op.create_index("idx_chunks_search_tsv", "chunks", ["search_tsv"], unique=False, postgresql_using="gin")

    op.create_table(
        "ingest_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("document_versions.id"), nullable=False),
        sa.Column("task_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("progress", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("progress >= 0 AND progress <= 100", name="ck_ingest_tasks_progress_range"),
    )
    op.create_index("idx_ingest_tasks_document_id", "ingest_tasks", ["document_id"], unique=False)
    op.create_index("idx_ingest_tasks_version_id", "ingest_tasks", ["version_id"], unique=False)
    op.create_index("idx_ingest_tasks_status", "ingest_tasks", ["status"], unique=False)
    op.create_index("idx_ingest_tasks_task_type", "ingest_tasks", ["task_type"], unique=False)
    op.create_index("idx_ingest_tasks_created_at", "ingest_tasks", [sa.text("created_at DESC")], unique=False)

    op.create_table(
        "eval_run_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("eval_runs.id"), nullable=False),
        sa.Column("dataset_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("eval_dataset_items.id"), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("retrieved_chunk_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("reranked_chunk_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("refusal_triggered", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
        sa.Column("recall_hit", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
        sa.Column("reciprocal_rank", sa.Numeric(10, 4), nullable=True),
        sa.Column("citation_passed", sa.Boolean(), nullable=True),
        sa.Column("groundedness_score", sa.Numeric(10, 4), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("idx_eval_run_items_run_id", "eval_run_items", ["run_id"], unique=False)
    op.create_index("idx_eval_run_items_dataset_item_id", "eval_run_items", ["dataset_item_id"], unique=False)
    op.create_index("idx_eval_run_items_refusal_triggered", "eval_run_items", ["refusal_triggered"], unique=False)
    op.create_index("idx_eval_run_items_citation_passed", "eval_run_items", ["citation_passed"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_eval_run_items_citation_passed", table_name="eval_run_items")
    op.drop_index("idx_eval_run_items_refusal_triggered", table_name="eval_run_items")
    op.drop_index("idx_eval_run_items_dataset_item_id", table_name="eval_run_items")
    op.drop_index("idx_eval_run_items_run_id", table_name="eval_run_items")
    op.drop_table("eval_run_items")

    op.drop_index("idx_ingest_tasks_created_at", table_name="ingest_tasks")
    op.drop_index("idx_ingest_tasks_task_type", table_name="ingest_tasks")
    op.drop_index("idx_ingest_tasks_status", table_name="ingest_tasks")
    op.drop_index("idx_ingest_tasks_version_id", table_name="ingest_tasks")
    op.drop_index("idx_ingest_tasks_document_id", table_name="ingest_tasks")
    op.drop_table("ingest_tasks")

    op.drop_index("idx_chunks_search_tsv", table_name="chunks")
    op.drop_index("idx_chunks_keywords_gin", table_name="chunks")
    op.drop_index("idx_chunks_security_domain_gin", table_name="chunks")
    op.drop_index("idx_chunks_metadata_gin", table_name="chunks")
    op.drop_index("idx_chunks_page_end", table_name="chunks")
    op.drop_index("idx_chunks_page_start", table_name="chunks")
    op.drop_index("idx_chunks_article_no", table_name="chunks")
    op.drop_index("idx_chunks_parent_chunk_id", table_name="chunks")
    op.drop_index("idx_chunks_chunk_hash", table_name="chunks")
    op.drop_index("idx_chunks_is_active", table_name="chunks")
    op.drop_index("idx_chunks_chunk_type", table_name="chunks")
    op.drop_index("idx_chunks_doc_type", table_name="chunks")
    op.drop_index("idx_chunks_version_id", table_name="chunks")
    op.drop_index("idx_chunks_document_id", table_name="chunks")
    op.drop_table("chunks")

    op.drop_index("idx_eval_runs_created_at", table_name="eval_runs")
    op.drop_index("idx_eval_runs_status", table_name="eval_runs")
    op.drop_index("idx_eval_runs_dataset_id", table_name="eval_runs")
    op.drop_table("eval_runs")

    op.drop_index("idx_eval_dataset_items_expected_keywords_gin", table_name="eval_dataset_items")
    op.drop_index("idx_eval_dataset_items_expected_doc_type", table_name="eval_dataset_items")
    op.drop_index("idx_eval_dataset_items_dataset_id", table_name="eval_dataset_items")
    op.drop_table("eval_dataset_items")

    op.drop_index("idx_feedback_score", table_name="feedback")
    op.drop_index("idx_feedback_query_log_id", table_name="feedback")
    op.drop_table("feedback")

    op.drop_constraint("fk_documents_current_version_id_document_versions", "documents", type_="foreignkey")

    op.drop_index("idx_document_versions_file_hash", table_name="document_versions")
    op.drop_index("idx_document_versions_publish_date", table_name="document_versions")
    op.drop_index("idx_document_versions_effective_date", table_name="document_versions")
    op.drop_index("idx_document_versions_version_status", table_name="document_versions")
    op.drop_index("idx_document_versions_document_id", table_name="document_versions")
    op.drop_table("document_versions")

    op.drop_index("idx_eval_datasets_created_at", table_name="eval_datasets")
    op.drop_index("idx_eval_datasets_status", table_name="eval_datasets")
    op.drop_table("eval_datasets")

    op.drop_index("idx_query_logs_filters_gin", table_name="query_logs")
    op.drop_index("idx_query_logs_risk_type", table_name="query_logs")
    op.drop_index("idx_query_logs_safety_action", table_name="query_logs")
    op.drop_index("idx_query_logs_intent", table_name="query_logs")
    op.drop_index("idx_query_logs_created_at", table_name="query_logs")
    op.drop_table("query_logs")

    op.drop_index("idx_documents_tags_gin", table_name="documents")
    op.drop_index("idx_documents_security_domain_gin", table_name="documents")
    op.drop_index("idx_documents_current_version_id", table_name="documents")
    op.drop_index("idx_documents_created_at", table_name="documents")
    op.drop_index("idx_documents_status", table_name="documents")
    op.drop_index("idx_documents_doc_type", table_name="documents")
    op.drop_table("documents")
