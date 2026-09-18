import datetime
import logging
import mimetypes
import os
import uuid

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import Http404, FileResponse, HttpResponse
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from django.shortcuts import render, redirect
from django.utils import timezone

from core.decorators import ensure_registration_gate
from review_by_tutor.utils.contact_form import handle_send_notification
from review_by_tutor.views import _staff_check
from .ctx_builders import merge_context, base_user_context
from .access import (
    available_documents_for,
    available_document_types_for,
    ensure_document_available,
    ensure_document_type_available,
)
from .decorators import rate_limit_uploads
from .forms import DocumentUploadForm, SlotDocumentUploadForm, AttachDocumentsForm, build_params_form
from .models import Document, DocumentInstruction, DocumentType, DocTemplate
from .services import render_docx_bytes
from scholar_form.services.yandex_disk import (
    YandexDiskError,
    build_document_disk_path,
    get_download_url,
    upload_file_to_yandex_disk,
)

logger = logging.getLogger(__name__)

User = get_user_model()


@login_required
def serve_document(request, document_id):
    document = get_object_or_404(Document.objects.select_related("document_type"), pk=document_id)
    if request.user == document.user or request.user.is_staff:
        if not request.user.is_staff:
            ensure_document_available(request.user, document)
        if document.yandex_disk_path:
            try:
                return redirect(get_download_url(
                    document.yandex_disk_path,
                    log_context={"user_id": document.user_id, "document_id": document.pk},
                ))
            except YandexDiskError as exc:
                logger.warning("Не удалось получить документ с Яндекс Диска document_id=%s: %s", document.pk, exc)
                raise Http404("Документ временно недоступен.") from exc

        if not document.file:
            raise Http404("Документ не найден.")
        file_path = document.file.path

        if not os.path.exists(file_path):
            logger.info('Документ не найден на сервере. ')
            raise Http404("Документ не найден на сервере.")

        try:
            content_type, encoding = mimetypes.guess_type(file_path)

            if content_type is None:
                content_type = 'application/octet-stream'

            response = FileResponse(open(file_path, 'rb'),
                                    content_type=content_type)

            response['Content-Disposition'] = f'inline; filename="{document.file.name.split("/")[-1]}"'

            return response
        except FileNotFoundError:
            logger.info('Файл документа не найден на сервере.')
            raise Http404("Файл документа не найден.")
        except Exception as e:
            logger.error(f"Ошибка при отдаче файла: {e}")
            raise Http404("Произошла ошибка при попытке открыть документ.")
    else:
        logger.info(
            f'Пользователь {request.user.username} пытается получить доступ к документам {document.user.username}')
        raise Http404("У вас нет доступа к этому документу.")


@ensure_registration_gate('protected')
@login_required
@rate_limit_uploads(rate_limit_seconds=1, max_uploads=1)
def documents_dashboard(request):
    all_user_documents = available_documents_for(
        request.user,
        Document.objects.filter(user=request.user, uploaded_by_staff=False, is_deleted=False),
    ).order_by('-uploaded_at')
    user_documents = all_user_documents.filter(document_type__isnull=True)
    staff_documents = Document.objects.filter(user=request.user, uploaded_by_staff=True, is_deleted=False).order_by(
        '-uploaded_at')
    slot_document_qs = available_documents_for(
        request.user,
        Document.objects.filter(user=request.user, uploaded_by_staff=False, is_deleted=False),
    ).order_by('-uploaded_at')
    document_types = available_document_types_for(
        request.user,
        DocumentType.objects.filter(is_active=True),
    ).prefetch_related(
        Prefetch('documents', queryset=slot_document_qs, to_attr='user_slot_documents')
    )
    archived_slot_documents = all_user_documents.filter(document_type__is_active=False).select_related('document_type')

    document_upload_form = DocumentUploadForm()
    slot_upload_form = SlotDocumentUploadForm()

    attach_documents_form = AttachDocumentsForm(user=request.user)

    if request.method == 'POST':
        if request.POST.get('form_type') == 'slot_document_form':
            document_type = get_object_or_404(
                DocumentType,
                pk=request.POST.get('document_type_id'),
                is_active=True,
            )
            ensure_document_type_available(request.user, document_type)
            form = SlotDocumentUploadForm(
                request.POST,
                request.FILES,
                instance=Document(
                    user=request.user,
                    document_type=document_type,
                    caption=document_type.name,
                ),
            )
            if form.is_valid():
                document = form.save(commit=False)
                uploaded_file = form.cleaned_data["file"]
                disk_path = build_document_disk_path(
                    request.user, uploaded_file.name, unique_suffix=uuid.uuid4().hex[:8]
                )
                try:
                    upload_file_to_yandex_disk(
                        uploaded_file=uploaded_file,
                        disk_path=disk_path,
                        log_context={"user_id": request.user.id, "asset": "document"},
                    )
                except YandexDiskError as exc:
                    logger.warning("Ошибка загрузки документа слота на Яндекс Диск user_id=%s: %s", request.user.id, exc)
                    messages.error(request, "Не удалось загрузить документ на Яндекс Диск. Попробуйте ещё раз.")
                    slot_upload_form = form
                else:
                    document.user_file_name = uploaded_file.name
                    document.file = ""
                    document.yandex_disk_path = disk_path
                    document.yandex_disk_uploaded_at = timezone.now()
                    document.yandex_disk_error = ""
                    document.save()
                    messages.success(request, f'Документ «{document_type.name}» успешно загружен!')
                    return redirect('documents_dashboard')
            else:
                messages.error(request, 'Ошибка при загрузке документа. Проверьте выбранный файл.')
                slot_upload_form = form
        elif request.POST.get('form_type') == 'general_document_form':
            form = DocumentUploadForm(request.POST, request.FILES)
            if form.is_valid():
                document = form.save(commit=False)
                document.user = request.user
                uploaded_file = form.cleaned_data["file"]
                disk_path = build_document_disk_path(
                    request.user, uploaded_file.name, unique_suffix=uuid.uuid4().hex[:8]
                )
                try:
                    upload_file_to_yandex_disk(
                        uploaded_file=uploaded_file,
                        disk_path=disk_path,
                        log_context={"user_id": request.user.id, "asset": "document"},
                    )
                except YandexDiskError as exc:
                    logger.warning("Ошибка загрузки документа на Яндекс Диск user_id=%s: %s", request.user.id, exc)
                    messages.error(request, "Не удалось загрузить документ на Яндекс Диск. Попробуйте ещё раз.")
                    document_upload_form = form
                else:
                    document.user_file_name = uploaded_file.name
                    document.file = ""
                    document.yandex_disk_path = disk_path
                    document.yandex_disk_uploaded_at = timezone.now()
                    document.yandex_disk_error = ""
                    document.save()
                    messages.success(request, 'Документ успешно загружен!')
                    logger.info('%s загрузил файл %s на Яндекс Диск', request.user.username, document.user_file_name)
                    return redirect('documents_dashboard')
            else:
                logger.info(f'Неверное заполнение формы загрузки документа')
                messages.error(request, 'Ошибка при загрузке общего документа. Пожалуйста, проверьте форму.')
                document_upload_form = form
        elif request.POST.get('form_type') == 'attach_documents_form':
            document_id = request.POST.get('target_document_id')
            if not document_id:
                messages.error(request, 'Не указан целевой документ для прикрепления.')
                return redirect('documents_dashboard')

            target_document = get_object_or_404(Document, pk=document_id, user=request.user, uploaded_by_staff=True)

            selected_documents_ids = request.POST.getlist('documents_to_attach')
            form_data = request.POST.copy()
            form_data.setlist('documents_to_attach', selected_documents_ids)

            form = AttachDocumentsForm(form_data, user=request.user)
            if form.is_valid():
                selected_documents = form.cleaned_data['documents_to_attach']
                target_document.related_documents.set(selected_documents)

                target_document.status = 'PENDING'
                target_document.save()

                messages.success(request, f'Документы успешно прикреплены к "{target_document.caption}".')
                logger.info(f'{request.user.username} прикрепил документы к {target_document.caption}')
                return redirect('documents_dashboard')
            else:
                messages.error(request, 'Ошибка при прикреплении документов. Пожалуйста, проверьте форму.')
                logger.error('Ошибка при прикреплении документов')
                attach_documents_form = form
        else:
            logger.error(f'{request.user.username} неизвестный тип формы')
            messages.error(request, 'Неизвестный тип формы.')

    context = {
        'general_document_form': document_upload_form,
        'slot_upload_form': slot_upload_form,
        'document_types': document_types,
        'archived_slot_documents': archived_slot_documents,
        'user_documents': user_documents,
        'has_user_documents': all_user_documents.exists(),
        'staff_documents': staff_documents,
        'attach_documents_form': attach_documents_form,
        'document_instruction': DocumentInstruction.get_current(),
        'active': 'documents_dashboard',
    }
    return render(request, 'documents/documents_dashboard.html', context)


@login_required
def delete_document(request, document_id):
    document = get_object_or_404(
        Document.objects.select_related("document_type"),
        pk=document_id,
        user=request.user,
    )
    ensure_document_available(request.user, document)

    document.is_deleted = True
    document.save()
    messages.success(request, 'Документ успешно удален.')
    logger.info('Файл %s помечен как удалённый', document.user_file_name or document.file.name)
    return redirect('documents_dashboard')


@login_required
@user_passes_test(_staff_check)
def template_params(request, template_id, user_id):
    tpl = get_object_or_404(DocTemplate, pk=template_id, is_active=True)
    target_user = get_object_or_404(User, pk=user_id)
    ParamsForm = build_params_form(tpl.required_params)

    if request.method == "POST":
        form = ParamsForm(request.POST)
        if form.is_valid():
            extra = form.cleaned_data
            context = merge_context(base_user_context(target_user), extra)
            context = merge_context(context, {"date": datetime.date.today()})

            filename = f"{tpl.id}_{target_user.username or target_user.id}_{datetime.date.today():%Y%m%d}.docx"
            content = render_docx_bytes(tpl.file, context)

            resp = HttpResponse(
                content,
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
            resp["Content-Disposition"] = f'attachment; filename="{filename}"'
            resp["Content-Length"] = str(len(content))
            return resp
    else:
        initial = {}
        for k, meta in (tpl.required_params or {}).items():
            if (meta or {}).get("type") == "date":
                initial[k] = datetime.date.today().isoformat()
        form = ParamsForm(initial=initial)

    return render(request, "staff_templates/docs/template_params.html", {
        "template": tpl,
        "personal": target_user.personal_data,
        "form": form,
        "user_obj": get_object_or_404(User, pk=user_id),
    })


@login_required
@user_passes_test(_staff_check)
def template_list(request, user_id):
    templates = DocTemplate.objects.filter(is_active=True).order_by("name")
    send_notification_form = handle_send_notification(request, User.objects.get(pk=user_id))
    return render(request, "staff_templates/docs/templates.html",
                  {"templates": templates, "active": "documents_templates",
                   "user_obj": get_object_or_404(User, pk=user_id), "send_notification_form": send_notification_form,
})
