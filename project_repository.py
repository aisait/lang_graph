"""
project_repository.py - Capa de persistencia para las tablas project_* en CTFOM.
31JUL2026
"""
import json
import asyncpg
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

class ProjectRepository:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    # =========================================================================
    # DEFINICIÓN DEL PROYECTO
    # =========================================================================
    async def create_definition(self, thread_id: str, consent_hash: str = "") -> bool:
        async with self.pool.acquire() as conn:
            try:
                await conn.execute("""
                    INSERT INTO project_definitions (thread_id, consent_hash, consent_given)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (thread_id) DO UPDATE
                    SET updated_at = now(), is_active = TRUE
                """, thread_id, consent_hash, True)
                dimensions = ['IDENTIDAD', 'PROBLEMA', 'TECNICA', 'COMPORTAMIENTO', 'VIABILIDAD', 'SINTESIS']
                for dim in dimensions:
                    await conn.execute("""
                        INSERT INTO project_states (thread_id, dimension, completeness, confidence)
                        VALUES ($1, $2, 0.0, 0.0)
                        ON CONFLICT (thread_id, dimension) DO NOTHING
                    """, thread_id, dim)
                logger.info(f"Proyecto creado para thread_id {thread_id}")
                return True
            except Exception as e:
                logger.error(f"Error creando definición: {e}")
                return False

    async def get_definition(self, thread_id: str) -> Optional[Dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM project_definitions WHERE thread_id = $1", thread_id)
            return dict(row) if row else None

    async def update_definition(self, thread_id: str, data: Dict):
        async with self.pool.acquire() as conn:
            fields = []
            values = []
            i = 2
            for key, val in data.items():
                fields.append(f"{key} = ${i}")
                values.append(val)
                i += 1
            if not fields:
                return
            query = f"UPDATE project_definitions SET {', '.join(fields)}, updated_at = now() WHERE thread_id = $1"
            await conn.execute(query, thread_id, *values)

    # =========================================================================
    # ESTADOS POR DIMENSIÓN
    # =========================================================================
    async def get_state(self, thread_id: str, dimension: str) -> Optional[Dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM project_states WHERE thread_id = $1 AND dimension = $2", thread_id, dimension)
            return dict(row) if row else None

    async def update_state(self, thread_id: str, dimension: str, data: Dict):
        async with self.pool.acquire() as conn:
            existing = await self.get_state(thread_id, dimension)
            if existing:
                variables = existing.get('variables', {})
                if isinstance(variables, dict):
                    variables.update(data.get('variables', {}))
                else:
                    variables = data.get('variables', {})
            else:
                variables = data.get('variables', {})
            completeness = data.get('completeness', 0.0)
            confidence = data.get('confidence', 0.0)
            await conn.execute("""
                INSERT INTO project_states (thread_id, dimension, completeness, confidence, variables)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (thread_id, dimension) DO UPDATE
                SET completeness = $3, confidence = $4, variables = $5, last_updated = now()
            """, thread_id, dimension, completeness, confidence, json.dumps(variables))

    # =========================================================================
    # RESPUESTAS
    # =========================================================================
    async def add_answer(self, thread_id: str, question_id: str, answer_text: str,
                         answer_value: Any = None, answer_type: str = "text",
                         is_validated: bool = False, confidence_after: float = 0.0):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO project_answers (thread_id, question_id, answer_text, answer_value,
                                            is_validated, confidence_after, answer_type)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
            """, thread_id, question_id, answer_text,
                json.dumps(answer_value) if answer_value else None,
                is_validated, confidence_after, answer_type)

    async def get_answers(self, thread_id: str) -> List[Dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM project_answers WHERE thread_id = $1 ORDER BY timestamp", thread_id)
            return [dict(row) for row in rows]

    # =========================================================================
    # INCIDENTES (BEI/CIT)
    # =========================================================================
    async def add_incident(self, thread_id: str, narrative: str, impact_loss_gtq: float = None,
                           duration_hours: float = None, resolution: str = None,
                           emotion_tag: str = None, frequency_per_year: int = None):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO project_incidents (thread_id, narrative, impact_loss_gtq, duration_hours,
                                              resolution, emotion_tag, frequency_per_year)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
            """, thread_id, narrative, impact_loss_gtq, duration_hours,
                resolution, emotion_tag, frequency_per_year)

    async def get_incidents(self, thread_id: str) -> List[Dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM project_incidents WHERE thread_id = $1 ORDER BY timestamp", thread_id)
            return [dict(row) for row in rows]

    # =========================================================================
    # JTBD (JOBS)
    # =========================================================================
    async def add_job(self, thread_id: str, functional_job: str = None,
                      emotional_job: str = None, social_job: str = None, priority: int = 1):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO project_jobs (thread_id, functional_job, emotional_job, social_job, priority)
                VALUES ($1, $2, $3, $4, $5)
            """, thread_id, functional_job, emotional_job, social_job, priority)

    async def get_jobs(self, thread_id: str) -> List[Dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM project_jobs WHERE thread_id = $1 ORDER BY priority DESC", thread_id)
            return [dict(row) for row in rows]

    # =========================================================================
    # OUTCOMES (ODI)
    # =========================================================================
    async def add_outcome(self, thread_id: str, metric_name: str,
                          current_state: float, desired_state: float,
                          importance: float = 1.0):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO project_outcomes (thread_id, metric_name, current_state,
                                             desired_state, importance)
                VALUES ($1, $2, $3, $4, $5)
            """, thread_id, metric_name, current_state, desired_state, importance)

    async def get_outcomes(self, thread_id: str) -> List[Dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM project_outcomes WHERE thread_id = $1 ORDER BY importance DESC", thread_id)
            return [dict(row) for row in rows]

    # =========================================================================
    # VPC
    # =========================================================================
    async def update_vpc(self, thread_id: str, pains: List[str] = None,
                         gains: List[str] = None, jobs: List[str] = None,
                         pain_relievers: List[str] = None, gain_creators: List[str] = None):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO project_vpc (thread_id, pains, gains, jobs, pain_relievers, gain_creators)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (id) DO UPDATE SET
                    pains = EXCLUDED.pains,
                    gains = EXCLUDED.gains,
                    jobs = EXCLUDED.jobs,
                    pain_relievers = EXCLUDED.pain_relievers,
                    gain_creators = EXCLUDED.gain_creators,
                    timestamp = now()
            """, thread_id, pains or [], gains or [], jobs or [], pain_relievers or [], gain_creators or [])

    # =========================================================================
    # KANO
    # =========================================================================
    async def add_kano_feature(self, thread_id: str, feature_name: str, category: str):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO project_kano (thread_id, feature_name, category)
                VALUES ($1, $2, $3)
            """, thread_id, feature_name, category)

    async def get_kano_features(self, thread_id: str) -> List[Dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM project_kano WHERE thread_id = $1 ORDER BY id", thread_id)
            return [dict(row) for row in rows]

    # =========================================================================
    # ESPECIFICACIONES
    # =========================================================================
    async def add_spec(self, thread_id: str, spec_name: str,
                       category: str, priority_score: float = 0.0):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO project_specs (thread_id, spec_name, category, priority_score)
                VALUES ($1, $2, $3, $4)
            """, thread_id, spec_name, category, priority_score)

    async def get_specs(self, thread_id: str) -> List[Dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM project_specs WHERE thread_id = $1 ORDER BY priority_score DESC", thread_id)
            return [dict(row) for row in rows]

    # =========================================================================
    # PERFIL
    # =========================================================================
    async def update_profile(self, thread_id: str, draft_text: str = None,
                             final_text: str = None, technical_text: str = None,
                             research_text: str = None):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO project_profiles (thread_id, draft_text, final_text,
                                             technical_text, research_text)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (thread_id) DO UPDATE SET
                    draft_text = EXCLUDED.draft_text,
                    final_text = EXCLUDED.final_text,
                    technical_text = EXCLUDED.technical_text,
                    research_text = EXCLUDED.research_text,
                    generated_at = now(),
                    version = project_profiles.version + 1
            """, thread_id, draft_text, final_text, technical_text, research_text)

    async def get_profile(self, thread_id: str) -> Optional[Dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM project_profiles WHERE thread_id = $1", thread_id)
            return dict(row) if row else None

    # =========================================================================
    # SESIONES
    # =========================================================================
    async def start_session(self, thread_id: str, completeness_at_start: float = 0.0) -> int:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO project_sessions (thread_id, session_start, completeness_at_start)
                VALUES ($1, now(), $2) RETURNING id
            """, thread_id, completeness_at_start)
            return row['id'] if row else 0

    async def end_session(self, session_id: int, message_count: int = 0,
                          completeness_at_end: float = 0.0, interrupted: bool = False,
                          interrupted_by: str = None):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE project_sessions
                SET session_end = now(),
                    message_count = $2,
                    completeness_at_end = $3,
                    duration_seconds = EXTRACT(EPOCH FROM (now() - session_start)),
                    interrupted = $4,
                    interrupted_by = $5
                WHERE id = $1
            """, session_id, message_count, completeness_at_end, interrupted, interrupted_by)
