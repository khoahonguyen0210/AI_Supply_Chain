package com.scm.platform.document;

import com.scm.platform.document.DocumentRepository.DocumentDetail;
import com.scm.platform.document.DocumentRepository.DocumentSummary;
import com.scm.platform.error.ApiException;
import com.scm.platform.mlservice.MlEngineClient;
import com.scm.platform.security.Actor;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import java.time.LocalDate;
import java.util.List;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

@RestController
@RequestMapping("/api/documents")
public class DocumentController {

	private final DocumentRepository documents;

	private final MlEngineClient engine;

	private final JsonMapper json;

	public DocumentController(DocumentRepository documents, MlEngineClient engine, JsonMapper json) {
		this.documents = documents;
		this.engine = engine;
		this.json = json;
	}

	public record AskRequest(@NotBlank @Size(min = 3, max = 500) String question) {
	}

	@GetMapping
	public List<DocumentSummary> list(Actor actor, @RequestParam(required = false) String docType,
			@RequestParam(required = false) String supplierId,
			@RequestParam(defaultValue = "false") boolean includeSuperseded,
			@RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate asOf) {
		return documents.list(actor.role(), asOf == null ? LocalDate.now() : asOf, docType, supplierId,
				includeSuperseded);
	}

	/** Unreadable documents get a 404, so restricted ones are not revealed. */
	@GetMapping("/{documentId}")
	public DocumentDetail get(Actor actor, @PathVariable String documentId,
			@RequestParam(required = false) String version,
			@RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate asOf) {
		return documents.find(actor.role(), documentId, version, asOf == null ? LocalDate.now() : asOf)
				.orElseThrow(() -> ApiException.notFound("UNKNOWN_DOCUMENT", "no document " + documentId));
	}

	@PostMapping("/ask")
	public JsonNode ask(Actor actor, @Valid @RequestBody AskRequest request) {
		return engine.askDocuments(actor, json.valueToTree(request));
	}

}
