# -*- coding: utf-8 -*-
# Code for Life
#
# Copyright (C) 2017, Ocado Innovation Limited
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# ADDITIONAL TERMS – Section 7 GNU General Public Licence
#
# This licence does not grant any right, title or interest in any “Ocado” logos,
# trade names or the trademark “Ocado” or any other trademarks or domain names
# owned by Ocado Innovation Limited or the Ocado group of companies or any other
# distinctive brand features of “Ocado” as may be secured from time to time. You
# must not distribute any modification of this program using the trademark
# “Ocado” or claim any affiliation or association with Ocado or its employees.
#
# You are not authorised to use the name Ocado (or any of its trade names) or
# the names of any author or contributor in advertising or for publicity purposes
# pertaining to the distribution of this program, without the prior written
# authorisation of Ocado.
#
# Any propagation, distribution or conveyance of this program must include this
# copyright notice and these terms. You must not misrepresent the origins of this
# program; modified versions of the program must be marked as such and not
# identified as the original program.
import json

from datetime import timedelta

from django.conf import settings
from django.shortcuts import render, get_object_or_404
from django.http import HttpResponse, HttpResponseRedirect, Http404
from django.core.urlresolvers import reverse_lazy
from django.contrib import messages as messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.staticfiles.storage import staticfiles_storage
from django.utils import timezone

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.colors import black, white
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle

from portal.models import Class, Student, Teacher
from portal.forms.teach_new import ClassCreationForm, StudentCreationForm, ClassMoveForm, ClassEditForm, \
    TeacherEditStudentForm, TeacherSetStudentPass
from portal.permissions import logged_in_as_teacher
from portal.helpers.generators import generate_access_code, generate_password
from portal.views.teacher.pdfs import PDF_DATA
from portal.templatetags.app_tags import cloud_storage


@login_required(login_url=reverse_lazy('login_new'))
@user_passes_test(logged_in_as_teacher, login_url=reverse_lazy('login_new'))
def materials_viewer_new(request, pdf_name):

    def _getLinks():
        links = PDF_DATA[pdf_name]['links']
        link_titles = []
        for link in links:
            link = link.replace('_', ' ').title()

            if (link[0] == 'K') | (link[1] == 'k'):
                link = link[:4].upper() + link[4:]

            link_titles.append(link)

        return zip(links, link_titles)

    try:
        title = PDF_DATA[pdf_name]['title']
        description = PDF_DATA[pdf_name]['description']
        url = cloud_storage(PDF_DATA[pdf_name]['url'])
        page_origin = PDF_DATA[pdf_name]['page_origin']

    except KeyError:
        raise Http404

    if PDF_DATA[pdf_name]['links'] is not None:
        links = _getLinks()
    else:
        links = None

    if 'video' in PDF_DATA[pdf_name]:
        video_link = PDF_DATA[pdf_name]['video']
        video_download_link = cloud_storage(PDF_DATA[pdf_name]['video_download_link'])
    else:
        video_link = None
        video_download_link = None

    return render(request, 'redesign/teach_new/viewer_new.html',
                  {'title': title,
                   'description': description,
                   'url': url,
                   'links': links,
                   'video_link': video_link,
                   'video_download_link': video_download_link,
                   'page_origin': page_origin})


@login_required(login_url=reverse_lazy('login_new'))
@user_passes_test(logged_in_as_teacher, login_url=reverse_lazy('login_new'))
def teacher_classes_new(request):
    teacher = request.user.new_teacher
    requests = Student.objects.filter(pending_class_request__teacher=teacher)

    if not teacher.school:
        return HttpResponseRedirect(reverse_lazy('onboarding-organisation'))

    if request.method == 'POST':
        form = ClassCreationForm(request.POST)
        if form.is_valid():
            created_class = create_class_new(form, teacher)
            messages.success(request, "The class '{className}' has been created successfully."
                             .format(className=created_class.name))
            return HttpResponseRedirect(reverse_lazy('onboarding-class', kwargs={'access_code': created_class.access_code}))
    else:
        form = ClassCreationForm(initial={'classmate_progress': 'False'})

    classes = Class.objects.filter(teacher=teacher)

    return render(request, 'redesign/teach_new/onboarding_classes.html',
                  {'form': form,
                   'classes': classes,
                   'requests': requests})


def create_class_new(form, teacher):
    classmate_progress = False
    if form.cleaned_data['classmate_progress'] == 'True':
        classmate_progress = True
    klass = Class.objects.create(
        name=form.cleaned_data['class_name'],
        teacher=teacher,
        access_code=generate_access_code(),
        classmates_data_viewable=classmate_progress)
    return klass


@login_required(login_url=reverse_lazy('login_new'))
@user_passes_test(logged_in_as_teacher, login_url=reverse_lazy('login_new'))
def teacher_class_new(request, access_code):
    klass = get_object_or_404(Class, access_code=access_code)
    teacher = request.user.new_teacher
    students = Student.objects.filter(class_field=klass).order_by('new_user__first_name')

    check_logged_in_students(klass, students)

    check_user_is_authorised(request, klass)

    if request.method == 'POST':
        new_students_form = StudentCreationForm(klass, request.POST)
        if new_students_form.is_valid():
            name_tokens = []
            for name in new_students_form.strippedNames:
                password = generate_password(6)
                name_tokens.append({'name': name, 'password': password})

                Student.objects.schoolFactory(
                    klass=klass,
                    name=name,
                    password=password)

            return render(request, 'redesign/teach_new/onboarding_print.html',
                          {'class': klass,
                           'name_tokens': name_tokens,
                           'query_data': json.dumps(name_tokens)})
    else:
        new_students_form = StudentCreationForm(klass)

    classes = Class.objects.filter(teacher=teacher)

    return render(request, 'redesign/teach_new/onboarding_students.html',
                  {'new_students_form': new_students_form,
                   'class': klass,
                   'classes': classes,
                   'students': students,
                   'num_students': len(students)})


def check_logged_in_students(klass, students):
    # Check which students are logged in
    logged_in_students = klass.get_logged_in_students()
    for student in students:
        if logged_in_students.filter(id=student.id).exists():
            student.logged_in = True
        else:
            student.logged_in = False


def check_user_is_authorised(request, klass):
    # check user authorised to see class
    if request.user.new_teacher != klass.teacher:
        raise Http404


@login_required(login_url=reverse_lazy('login_new'))
@user_passes_test(logged_in_as_teacher, login_url=reverse_lazy('login_new'))
def teacher_view_class(request, access_code):
    klass = get_object_or_404(Class, access_code=access_code)
    teacher = request.user.new_teacher
    students = Student.objects.filter(class_field=klass).order_by('new_user__first_name')

    check_logged_in_students(klass, students)

    check_user_is_authorised(request, klass)

    if request.method == 'POST':
        new_students_form = StudentCreationForm(klass, request.POST)
        if new_students_form.is_valid():
            name_tokens = []
            for name in new_students_form.strippedNames:
                password = generate_password(6)
                name_tokens.append({'name': name, 'password': password})

                Student.objects.schoolFactory(
                    klass=klass,
                    name=name,
                    password=password)

            return render(request, 'redesign/teach_new/onboarding_print.html',
                          {'class': klass,
                           'name_tokens': name_tokens,
                           'onboarding_done': True,
                           'query_data': json.dumps(name_tokens)})
    else:
        new_students_form = StudentCreationForm(klass)

    classes = Class.objects.filter(teacher=teacher)

    return render(request, 'redesign/teach_new/class_new.html',
                  {'class': klass,
                   'classes': classes,
                   'students': students,
                   'new_students_form': new_students_form,
                   'num_students': len(students)})


@login_required(login_url=reverse_lazy('login_new'))
@user_passes_test(logged_in_as_teacher, login_url=reverse_lazy('login_new'))
def teacher_delete_class_new(request, access_code):
    klass = get_object_or_404(Class, access_code=access_code)

    # check user authorised to see class
    if request.user.new_teacher != klass.teacher:
        raise Http404

    if Student.objects.filter(class_field=klass).exists():
        messages.info(request, 'This class still has students, please remove or delete them all before deleting the class.')
        return HttpResponseRedirect(reverse_lazy('view_class', kwargs={'access_code': access_code}))

    klass.delete()

    return HttpResponseRedirect(reverse_lazy('dashboard'))


@login_required(login_url=reverse_lazy('login_new'))
@user_passes_test(logged_in_as_teacher, login_url=reverse_lazy('login_new'))
def teacher_edit_class_new(request, access_code):
    klass = get_object_or_404(Class, access_code=access_code)

    # check user authorised to see class
    if request.user.new_teacher != klass.teacher:
        raise Http404

    external_requests_message = klass.get_requests_message()

    if request.method == 'POST':
        form = ClassEditForm(request.POST)
        if form.is_valid():
            return process_edit_class_form(request, klass, form)

    else:
        form = ClassEditForm(initial={
            'name': klass.name,
            'classmate_progress': klass.classmates_data_viewable,
        })

    return render(request, 'redesign/teach_new/teacher_edit_class_new.html',
                  {'form': form,
                   'class': klass,
                   'external_requests_message': external_requests_message})


def process_edit_class_form(request, klass, form):
    name = form.cleaned_data['name']
    classmate_progress = False

    if form.cleaned_data['classmate_progress'] == 'True':
        classmate_progress = True
    external_requests_setting = form.cleaned_data['external_requests']
    if external_requests_setting != '':
        # Change submitted for external requests
        hours = int(external_requests_setting)
        if hours == 0:
            # Setting to off
            klass.always_accept_requests = False
            klass.accept_requests_until = None
            messages.info(request, 'Class set successfully to never receive requests from external students.')
        elif hours < 1000:
            # Setting to number of hours
            klass.always_accept_requests = False
            klass.accept_requests_until = timezone.now() + timedelta(hours=hours)
            messages.info(request, 'Class set successfully to receive requests from external students until ' + klass.accept_requests_until.strftime("%d-%m-%Y %H:%M") + ' ' + timezone.get_current_timezone_name())
        else:
            # Setting to always on
            klass.always_accept_requests = True
            klass.accept_requests_until = None
            messages.info(request, 'Class set successfully to always receive requests from external students (not recommended)')

    klass.name = name
    klass.classmates_data_viewable = classmate_progress
    klass.save()

    messages.success(request, "The class's settings have been changed successfully.")

    return HttpResponseRedirect(reverse_lazy('view_class', kwargs={'access_code': klass.access_code}))


@login_required(login_url=reverse_lazy('login_new'))
@user_passes_test(logged_in_as_teacher, login_url=reverse_lazy('login_new'))
def teacher_edit_student_new(request, pk):
    student = get_object_or_404(Student, id=pk)

    check_if_authorised(request, student)

    name_form = TeacherEditStudentForm(student, initial={
        'name': student.new_user.first_name
    })

    password_form = TeacherSetStudentPass()
    set_password_mode = False

    if request.method == 'POST':
        if 'update_details' in request.POST:
            name_form = TeacherEditStudentForm(student, request.POST)
            if name_form.is_valid():
                name = name_form.cleaned_data['name']
                student.new_user.first_name = name
                student.new_user.save()
                student.save()

                messages.success(request, "The student's details have been changed successfully.")

        else:
            password_form = TeacherSetStudentPass(request.POST)
            if password_form.is_valid():
                return process_reset_password_form(request, student, password_form)
            set_password_mode = True

    return render(request, 'redesign/teach_new/teacher_edit_student_new.html', {
        'name_form': name_form,
        'password_form': password_form,
        'student': student,
        'class': student.class_field,
        'set_password_mode': set_password_mode,
    })


def process_reset_password_form(request, student, password_form):
    # check not default value for CharField
    new_password = password_form.cleaned_data['password']
    if new_password:
        student.new_user.set_password(new_password)
        student.new_user.save()
        name_pass = [{'name': student.new_user.first_name, 'password': new_password}]
        return render(request, 'redesign/teach_new/teacher_student_reset_new.html',
                      {'student': student,
                       'class': student.class_field,
                       'password': new_password,
                       'query_data': json.dumps(name_pass)})


def check_if_authorised(request, student):
    # check user is authorised to edit student
    if request.user.new_teacher != student.class_field.teacher:
        raise Http404


@login_required(login_url=reverse_lazy('login_new'))
@user_passes_test(logged_in_as_teacher, login_url=reverse_lazy('login_new'))
def teacher_student_reset_new(request, pk):
    student = get_object_or_404(Student, id=pk)

    # check user is authorised to edit student
    if request.user.new_teacher != student.class_field.teacher:
        raise Http404

    new_password = generate_password(6)
    student.new_user.set_password(new_password)
    student.new_user.save()
    name_pass = [{'name': student.new_user.first_name, 'password': new_password}]

    return render(request, 'redesign/teach_new/teacher_student_reset_new.html',
                  {'student': student,
                   'class': student.class_field,
                   'password': new_password,
                   'query_data': json.dumps(name_pass)})


@login_required(login_url=reverse_lazy('login_new'))
@user_passes_test(logged_in_as_teacher, login_url=reverse_lazy('login_new'))
def teacher_move_class_new(request, access_code):
    klass = get_object_or_404(Class, access_code=access_code)
    teachers = Teacher.objects.filter(school=klass.teacher.school).exclude(user=klass.teacher.user)

    # check user authorised to see class
    if request.user.new_teacher != klass.teacher:
        raise Http404

    if request.method == 'POST':
        form = ClassMoveForm(teachers, request.POST)
        if form.is_valid():
            teacher = form.cleaned_data['new_teacher']
            klass.teacher = get_object_or_404(Teacher, id=teacher)
            klass.save()

            messages.success(request, 'The class has been successfully assigned to a different teacher.')

            return HttpResponseRedirect(reverse_lazy('dashboard'))
    else:
        form = ClassMoveForm(teachers)
    return render(request, 'redesign/teach_new/teacher_move_class_new.html',
                  {'form': form,
                   'class': klass})


@login_required(login_url=reverse_lazy('login_new'))
@user_passes_test(logged_in_as_teacher, login_url=reverse_lazy('login_new'))
def teacher_print_reminder_cards_new(request, access_code):
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'filename="student_reminder_cards.pdf"'

    p = canvas.Canvas(response, pagesize=A4)

    # Define constants that determine the look of the cards
    PAGE_WIDTH, PAGE_HEIGHT = A4
    PAGE_MARGIN = PAGE_WIDTH / 32
    INTER_CARD_MARGIN = PAGE_WIDTH / 64
    CARD_PADDING = PAGE_WIDTH / 48

    NUM_X = 2
    NUM_Y = 4

    CARD_WIDTH = (PAGE_WIDTH - PAGE_MARGIN * 2 - INTER_CARD_MARGIN * (NUM_X - 1)) / NUM_X
    CARD_HEIGHT = (PAGE_HEIGHT - PAGE_MARGIN * 2 - INTER_CARD_MARGIN * (NUM_Y - 1)) / NUM_Y

    HEADER_HEIGHT = CARD_HEIGHT * 0.16
    FOOTER_HEIGHT = CARD_HEIGHT * 0.1

    CARD_INNER_WIDTH = CARD_WIDTH - CARD_PADDING * 2
    CARD_INNER_HEIGHT = CARD_HEIGHT - CARD_PADDING * 2 - HEADER_HEIGHT - FOOTER_HEIGHT

    CARD_IMAGE_WIDTH = CARD_INNER_WIDTH * 0.25

    CORNER_RADIUS = CARD_WIDTH / 32

    # Setup various character images to cycle round
    CHARACTER_FILES = ["portal/img/dee_large.png", "portal/img/kirsty_large.png", "portal/img/wes_large.png", "portal/img/nigel_large.png", "portal/img/phil_large.png"]
    CHARACTERS = []

    for character_file in CHARACTER_FILES:
        character_image = ImageReader(staticfiles_storage.path(character_file))
        character_height = CARD_INNER_HEIGHT
        character_width = CARD_IMAGE_WIDTH
        character_height = character_width * character_image.getSize()[1] / character_image.getSize()[0]
        if character_height > CARD_INNER_HEIGHT:
            character_height = CARD_INNER_HEIGHT
            character_width = character_height * character_image.getSize()[0] / character_image.getSize()[1]
        character = {'image': character_image, 'height': character_height, 'width': character_width}
        CHARACTERS.append(character)

    klass = get_object_or_404(Class, access_code=access_code)
    # Check auth
    if klass.teacher.new_user != request.user:
        raise Http404

    COLUMN_WIDTH = (CARD_INNER_WIDTH - CARD_IMAGE_WIDTH) * 0.45

    # Work out the data we're going to display, use data from the query string
    # if given, else display everyone in the class without passwords
    student_data = []

    student_data = get_student_data(request, klass, student_data)

    # Now draw everything
    x = 0
    y = 0

    def drawParagraph(text, position):
        style = ParagraphStyle('test')
        style.font = 'Helvetica-Bold'

        font_size = 16
        while font_size > 0:
            style.fontSize = font_size
            style.leading = font_size

            para = Paragraph(text, style)
            (para_width, para_height) = para.wrap(CARD_INNER_WIDTH - COLUMN_WIDTH - CARD_IMAGE_WIDTH, CARD_INNER_HEIGHT)

            if para_height <= 48:
                para.drawOn(p, inner_left + COLUMN_WIDTH, inner_bottom + CARD_INNER_HEIGHT * position + 8 - para_height / 2)
                return

            font_size -= 1

    current_student_count = 0
    for student in student_data:
        character_index = current_student_count % len(CHARACTERS)

        left = PAGE_MARGIN + x * CARD_WIDTH + x * INTER_CARD_MARGIN
        bottom = PAGE_HEIGHT - PAGE_MARGIN - (y + 1) * CARD_HEIGHT - y * INTER_CARD_MARGIN

        inner_left = left + CARD_PADDING
        inner_bottom = bottom + CARD_PADDING + FOOTER_HEIGHT

        header_bottom = bottom + CARD_HEIGHT - HEADER_HEIGHT
        footer_bottom = bottom

        # header rect
        p.setFillColorRGB(0.0, 0.027, 0.172)
        p.setStrokeColorRGB(0.0, 0.027, 0.172)
        p.roundRect(left, header_bottom, CARD_WIDTH, HEADER_HEIGHT, CORNER_RADIUS, fill=1)
        p.rect(left, header_bottom, CARD_WIDTH, HEADER_HEIGHT / 2, fill=1)

        # footer rect
        p.roundRect(left, bottom, CARD_WIDTH, FOOTER_HEIGHT, CORNER_RADIUS, fill=1)
        p.rect(left, bottom + FOOTER_HEIGHT / 2, CARD_WIDTH, FOOTER_HEIGHT / 2, fill=1)

        # outer box
        p.setStrokeColor(black)
        p.roundRect(left, bottom, CARD_WIDTH, CARD_HEIGHT, CORNER_RADIUS)

        # header text
        p.setFillColor(white)
        p.setFont('Helvetica', 18)
        p.drawCentredString(inner_left + CARD_INNER_WIDTH / 2, header_bottom + HEADER_HEIGHT * 0.35, '[ code ] for { life }')

        # footer text
        p.setFont('Helvetica', 10)
        p.drawCentredString(inner_left + CARD_INNER_WIDTH / 2, footer_bottom + FOOTER_HEIGHT * 0.32, settings.CODEFORLIFE_WEBSITE)

        # left hand side writing
        p.setFillColor(black)
        p.setFont('Helvetica', 12)
        p.drawString(inner_left, inner_bottom + CARD_INNER_HEIGHT * 0.12, 'Password:')
        p.drawString(inner_left, inner_bottom + CARD_INNER_HEIGHT * 0.45, 'Class Code:')
        p.drawString(inner_left, inner_bottom + CARD_INNER_HEIGHT * 0.78, 'Name:')

        # right hand side writing
        drawParagraph(student['password'], 0.10)
        drawParagraph(klass.access_code, 0.43)
        drawParagraph(student['name'], 0.76)

        # character image
        character = CHARACTERS[character_index]
        p.drawImage(character['image'], inner_left + CARD_INNER_WIDTH - character['width'], inner_bottom, character['width'], character['height'], mask='auto')

        x = (x + 1) % NUM_X
        compute_show_page(p, x, y, NUM_Y)
        current_student_count += 1

    compute_show_page(p, x, y, NUM_Y)

    p.save()
    return response


def get_student_data(request, klass, student_data):
    if request.method == 'POST':
        student_data = json.loads(request.POST.get('data', '[]'))

    else:
        students = Student.objects.filter(class_field=klass)

        for student in students:
            student_data.append({
                'name': student.new_user.first_name,
                'password': '__________',
            })

    return student_data


def compute_show_page(p, x, y, NUM_Y):
    if x == 0:
        y = (y + 1) % NUM_Y
        if y == 0:
            p.showPage()
    elif x != 0 or y != 0:
        p.showPage()