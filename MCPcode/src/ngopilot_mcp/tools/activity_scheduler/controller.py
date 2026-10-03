"""Durable orchestration for the independent activity Scheduler tool."""

from pathlib import Path

from ngopilot_mcp.shared.errors import InvalidJobStateError, InvalidRequestError
from ngopilot_mcp.shared.tool_api import ToolExecution

from .artifacts import FORMATS, validate_export
from .manifest import MANIFEST
from .schemas import INPUTS
from .state import projection
from .validation import validate_pdf, validate_reviews


class SchedulerController:
    async def execute(self, call, runtime):
        if call.operation not in INPUTS:
            raise InvalidRequestError("Unknown Scheduler operation.")
        data = INPUTS[call.operation].model_validate(call.input).model_dump(mode="json")
        if call.operation == "start":
            if call.job_id:
                raise InvalidRequestError("start does not accept job_id.")
            path = validate_pdf(data["pdf_path"])
            job = runtime.create_job(
                tool_name=MANIFEST.name, request_id=call.request_id, input_payload=data
            )
        else:
            if not call.job_id:
                raise InvalidRequestError("This operation requires job_id.")
            job = runtime.get_job(tool_name=MANIFEST.name, job_id=call.job_id)
            if call.operation == "status" and job.state == "exported":
                return runtime.job_execution(job=job, operation="status")
            if call.operation != "status" and call.operation not in job.next_operations:
                raise InvalidJobStateError(job.state, call.operation)
            if not job.result.get("source"):
                return runtime.job_execution(job=job, operation="status")
            if call.operation == "review":
                validate_reviews(job.result["activities"], data["reviews"])
        handle = runtime.begin_operation(
            job=job, operation=call.operation, request_id=call.request_id, payload=data
        )
        if handle.replay is not None:
            return ToolExecution(**handle.replay)
        try:
            payload = dict(data)
            if call.operation == "start":
                payload["pdf_path"] = str(
                    runtime.stage_file(
                        job=job,
                        role="activity_brochure",
                        source_path=path,
                        allowed_extensions=(".pdf",),
                        max_bytes=64 * 1024 * 1024,
                        content_kind="pdf",
                    )
                )
            else:
                payload["source"] = job.result["source"]
            result = await runtime.call_worker(
                worker=MANIFEST.worker,
                tool_name=MANIFEST.name,
                operation=call.operation,
                job=job,
                payload=payload,
            )
            state, next_ops = projection(result)
            artifacts = []
            if call.operation == "export":
                for kind, (artifact_kind, media) in FORMATS.items():
                    path = validate_export(Path(result["exports"][kind]), kind)
                    artifacts.append(
                        runtime.promote_artifact(
                            job=job,
                            source_path=path,
                            kind=artifact_kind,
                            media_type=media,
                            expected_extensions=("." + kind,),
                        )
                    )
                state, next_ops = "exported", ["status"]
            return runtime.complete_operation(
                job=job,
                handle=handle,
                state=state,
                native_status=state,
                result=result,
                native_refs={"source_id": result["source"]["id"]},
                artifacts=artifacts,
                warnings=result.get("warnings", []),
                next_operations=next_ops,
            )
        except Exception as exc:
            return runtime.fail_operation(
                job=job,
                handle=handle,
                error=exc,
                state=job.state if call.operation != "start" else "failed",
            )


CONTROLLER = SchedulerController()
