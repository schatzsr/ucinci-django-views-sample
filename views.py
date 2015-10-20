from django.shortcuts import HttpResponseRedirect, render
from django.views.generic import CreateView
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.core.mail import send_mass_mail
from django.forms import formset_factory
from rest_framework.views import APIView
from rest_framework.response import Response
from courses.models import BbMetaCourses, BbMetaLinkedCourses, InstructorCourses
from courses.serializers import InstructorCoursesSerializer
from courses.forms import MetaCoursesForm, UserLinkedCoursesFormSet, ForeignLinkedCoursesFormSet, \
    UpdateMetaLinkedCoursesFormset, RemoveMetaLinkedCoursesFormset, create_add_link_form


class InstructorCoursesList(APIView):
	"""
	Uses Django Rest Framework to allow intructors to dynamically search for courses based on instructor ID
	or course ID, and paginates the results.
	"""
	
    # I'm not sure if it would be more efficient to use pagination or simply slice the result list 
    # (e.g. having [:15] at the end of the query). Might not matter because QuerySets are lazy 
    # (query is actually run when QuerySet is evaluated). Will need to investigate this sometime.
    def get(self, request, format=None):
        search_user = request.query_params.get('search_user', None)
        search_course = request.query_params.get('search_course', None)

        if (search_user and search_course) is not None:
            instructorcourse_list = InstructorCourses.objects.filter(instructor_username__icontains=search_user,
                                                                     course_id__icontains=search_course)\
															 .values('course_id', 'instructor_username')
        elif search_user is not None:
            instructorcourse_list = InstructorCourses.objects.filter(instructor_username__icontains=search_user)\
															 .values('course_id', 'instructor_username')
        elif search_course is not None:
            instructorcourse_list = InstructorCourses.objects.filter(course_id__icontains=search_course)\
															 .values('course_id', 'instructor_username')
        
        paginator = Paginator(instructorcourse_list, 15)
        page = request.query_params.get('page')
        try:
            instructorcourses = paginator.page(page)
        except PageNotAnInteger:
            # If page is not an integer, deliver first page.
            instructorcourses = paginator.page(1)

        # Removing lines below to allow javascript to handle if the 'next' button is out of range
        #  for displaying the results.
        # except EmptyPage:
        #    # If page is out of range, deliver last page of results
        #    instructorcourses = paginator.page(paginator.num_pages)
        serializer = InstructorCoursesSerializer(instructorcourses, many=True)
        return Response(serializer.data)


class CreateMetaCourse(CreateView):
    """
    Creates a meta course based on user selection of child courses.
    The user must select at least one course they are teaching to create a meta course.
    """

    template_name = 'courses/create_meta_course.html'
    form_class = MetaCoursesForm
    success_url = '/status/'

    def get(self, request, *args, **kwargs):
        self.object = None
        form_class = self.get_form_class()  # i.e. MetaCourseForm
        form = self.get_form(form_class)
        user_courses_formset = UserLinkedCoursesFormSet(prefix='user_courses_formset')
        foreign_courses_formset = ForeignLinkedCoursesFormSet(prefix='foreign_courses_formset')

		# SHIBBOLETH USE
        # username = request.META['cn']  # 'cn' could also be replaced with 'REMOTE_USER'
		
        username = 'sean_s'  # FOR TESTING ONLY
        user_courses_list = InstructorCourses.objects.filter(instructor_username=username)\
            .values_list('course_id', flat=True).order_by('course_id')

        return self.render_to_response(self.get_context_data(form=form,
                                                             user_courses_formset=user_courses_formset,
                                                             foreign_courses_formset=foreign_courses_formset,
                                                             user_courses_list=user_courses_list))

    def post(self, request, *args, **kwargs):
        self.object = None
        form_class = self.get_form_class()
        form = self.get_form(form_class)
        user_courses_formset = UserLinkedCoursesFormSet(self.request.POST,
                                                        prefix='user_courses_formset',)
        foreign_courses_formset = ForeignLinkedCoursesFormSet(self.request.POST,
                                                           prefix='foreign_courses_formset')

        # SHIBBOLETH USE
		# username = request.META['cn']  # 'cn' could also be replaced with 'REMOTE_USER'
		
        username = 'sean_s'  # FOR TESTING ONLY
        if form.is_valid() and user_courses_formset.is_valid() and foreign_courses_formset.is_valid():
            return self.form_valid(username, form, user_courses_formset, foreign_courses_formset)
        else:
            return self.form_invalid(username, form, user_courses_formset, foreign_courses_formset)

    def form_valid(self, username, form, user_courses_formset, foreign_courses_formset):
        # This method is called when valid form data has been POSTed.
        # It should return an HttpResponse
        # e.g. form.send_email()
        #       return super(CreateMetaCourse, self).form.valid(form)

        # save(commit=False) returns an object that hasn't yet been saved to the database,
        # so we can do some processing before saving
        new_metacourse = form.save(commit=False)

        new_metacourse.instructor_id = username
        new_metacourse.meta_course_name = form.cleaned_data['meta_course_name'] + ' ' + '(' \
                                          + form.cleaned_data['sections'] + ')'
        new_metacourse.meta_course_id = 'meta_' + username + '_' + 'temp'
        new_metacourse.save()
        # First the instance has to be saved so a pk will be created,
        # then the meta_course_id is changed to include it.
        new_metacourse.meta_course_id = 'meta_' + username + '_' + str(new_metacourse.pk1)
        # Instance will be saved again below

        current_term = '00ZZ'

        for course_form in user_courses_formset:
            # Process each form in the formset by adding/changing the appropriate fields
            # and saving the new database instance.

            # If the submitted course_id exists in the db, then save the rest of the form
            # This kind of verification should probably be in an overridden clean() function in the form class
            #  declaration, but this just an easy/straightforward solution.
            child_course_exists = InstructorCourses.objects\
                .filter(course_id=course_form.cleaned_data['child_course']).exists()
            if child_course_exists:
                course_link = course_form.save(commit=False)
                # Because meta_course_pk1 is a foreign key, it must be set to the new MetaCourse instance itself,
                # instead of just its pk1 field (i.e. new_metacourse instead of new_metacourse.pk1)
                course_link.meta_course_pk1 = new_metacourse
                course_link.requestor = username
                course_link.child_course_instructor = username
                course_link.row_status = 0  # Enabled
                course_link.save()

                # This block is for finding the most recent term from the course_ids
                term = course_link.child_course[:4]
                if term[:2] > current_term[:2]:
                    current_term = term
                elif term[:2] == current_term[:2]:
                    if term[2] == 'F' and (current_term[2] == 'U' or current_term[2] == 'S'):
                        current_term = term
                    elif term[2] == 'U' and current_term[2] == 'S':
                        current_term = term

        email_recipients = {}  # Add instructor usernames as keys to this dict.
        email_subject = '[BB Meta Courses] New Request for Approval'
        email_message = 'An instructor has requested to use one of your courses in a Meta Course. ' \
                        + 'Please visit [URL REMOVED FROM PUBLIC CODE] to approve or deny this request. ' \
                        + 'If you have any questions or concerns, please contact the IT@UC Help Desk by ' \
                        + 'telephone at 513-556-HELP (4357) or by email at helpdesk@uc.edu.'

        for course_form in foreign_courses_formset:
            # This 'if' check assures that blank forms are not saved to the database
            if course_form.has_changed():

                # If the submitted course_id exists in the db, then save the rest of the form
                # This kind of verification should probably be in an overridden clean() function in the form class
                #  declaration, but this just an easy/straightforward solution.
                child_instructor = InstructorCourses.objects\
                    .filter(course_id=course_form.cleaned_data['child_course'])\
                    .values('instructor_username')
                if child_instructor:
                    course_link = course_form.save(commit=False)
                    course_link.meta_course_pk1 = new_metacourse
                    course_link.requestor = username
                    course_link.child_course_instructor = child_instructor[0]['instructor_username']
                    course_link.row_status = 1  # Pending
                    course_link.save()

                    # Find the most recent term from the course_ids
                    term = course_link.child_course[:4]
                    if term[:2] > current_term[:2]:
                        current_term = term
                    elif term[:2] == current_term[:2]:
                        if term[2] == 'F' and (current_term[2] == 'U' or current_term[2] == 'S'):
                            current_term = term
                        elif term[2] == 'U' and current_term[2] == 'S':
                            current_term = term

                    # Create email message that will be sent to instructors
                    foreign_instructor = course_link.child_course_instructor
                    if foreign_instructor not in email_recipients.keys():
                        # If the foreign_instructor isn't already a key in email_recipients,
                        #  add it along with its message.
                        foreign_instructor_email = foreign_instructor + '@ucmail.uc.edu'
                        # All messages must be in the format (subject, message, from_email, recipient_list)
                        email_recipients[foreign_instructor] = (email_subject, email_message, 'EMAIL REMOVED',
                                                                [foreign_instructor_email])

        new_metacourse.meta_course_name = '(Meta ' + current_term + ') ' + new_metacourse.meta_course_name
        self.object = new_metacourse  # self.object is a parameter of get_success_url, and cannot be None
        new_metacourse.save()

        # Prepare all the emails for sending. all_messages must be in the format (message1, message2, ...)
        all_messages = ()
        for recipient in email_recipients.keys():
            all_messages = all_messages + (email_recipients[recipient],)

        send_mass_mail(all_messages, fail_silently=False)

        return HttpResponseRedirect(self.get_success_url())

    def form_invalid(self, username, form, user_courses_formset, foreign_courses_formset):
        user_courses_list = InstructorCourses.objects.filter(instructor_username=username)\
            .values_list('course_id', flat=True).order_by('course_id')
        return self.render_to_response(self.get_context_data(form=form,
                                                             user_courses_formset=user_courses_formset,
                                                             foreign_courses_formset=foreign_courses_formset,
                                                             user_courses_list=user_courses_list))


# Sometimes making a function-based view is easier/more straightforward than using class-based.
# This is one of those cases, as we're dealing with formsets and multiple, existing database instances - something that
#  would prove to be tricky and complex using class-based views.
def approve_child_course(request):
    """
    Displays the child courses of the user's meta courses that are awaiting approval from other instructors,
     in addition to rendering formsets representing requests from other instructors to use the user's child courses,
     which the user can approve, deny, or leave pending.
    """
	# SHIBBOLETH USE
    # username = request.META['cn']  # 'cn' could also be replaced with 'REMOTE_USER'
	
    username = 'sean_s'  # FOR TESTING ONLY
    user_requested_courses_raw = BbMetaLinkedCourses.objects.filter(requestor=username).filter(row_status=1)\
        .values('meta_course_pk1__meta_course_name', 'child_course', 'child_course_instructor')
    # Courses the user has requested to be added to any meta course they created, that are awaiting approval.
    user_requested_courses = {}
    for course in user_requested_courses_raw:
        meta_name = course['meta_course_pk1__meta_course_name']
        if meta_name not in user_requested_courses.keys():
            user_requested_courses[meta_name] = [{'child_course': course['child_course'],
                                                 'child_course_instructor': course['child_course_instructor']}]
        else:
            user_requested_courses[meta_name].append({'child_course': course['child_course'],
                                                      'child_course_instructor': course['child_course_instructor']})

    if request.method == 'GET':
        formset = UpdateMetaLinkedCoursesFormset(queryset=BbMetaLinkedCourses.objects.filter(row_status=1)
                                                 .filter(child_course_instructor=username))

        context = {'formset': formset, 'user_requested_courses': user_requested_courses}

        return render(request, 'courses/status.html', context)

    if request.method == 'POST':
        formset = UpdateMetaLinkedCoursesFormset(request.POST)

        # Add instructor usernames as keys to this dict.
        email_recipients = {}

        for form in formset:
            if form.is_valid():
                linked_course = form.save(commit=False)
                row_status = linked_course.row_status
                child_course = linked_course.child_course
                requestor = linked_course.requestor
                requestor_email = requestor + '@ucmail.uc.edu'

                # If the user didn't select approve or deny for a course and submits, then the row_status field's value
                #  will be an empty string. When that happens, we need to make sure the instance's row_status remains
                #  at 1 (pending status).
                if (row_status != 0) and (row_status != 1) and (row_status != 2):
                    linked_course.row_status = 1

                elif row_status == 0:
                    email_subject = '[BB Meta Courses] One Of Your Requests Has Been Approved'
                    # Message contains the ID of the child course that was approved.
                    email_message = 'Your request to use {0} has been approved. '.format(child_course) + 'If you ' \
                                    + 'have any questions or concerns, please contact the IT@UC Help Desk by ' \
                                    + 'telephone at 513-556-HELP (4357) or by email at helpdesk@uc.edu.'
                    # Create approved email
                    if requestor in email_recipients.keys():
                        email_recipients[requestor] = email_recipients[requestor] + ((email_subject, email_message,
                                                                                      'EMAIL REMOVED',
                                                                                      [requestor_email]),)
                    else:
                        email_recipients[requestor] = ((email_subject, email_message,
                                                        'EMAIL REMOVED', [requestor_email]),)

                elif row_status == 2:
                    email_subject = '[BB Meta Courses] One Of Your Requests Has Been Denied'
                    # Message contains the ID of the child course that was denied.
                    email_message = 'Your request to use {0} has been Denied. '.format(child_course) + 'If you ' \
                                    + 'have any questions or concerns, please contact the IT@UC Help Desk by ' \
                                    + 'telephone at 513-556-HELP (4357) or by email at helpdesk@uc.edu.'
                    # Create denied email
                    if requestor in email_recipients.keys():
                        email_recipients[requestor] = email_recipients[requestor] + ((email_subject, email_message,
                                                                                      'EMAIL REMOVED',
                                                                                      [requestor_email]),)
                    else:
                        email_recipients[requestor] = ((email_subject, email_message,
                                                        'EMAIL REMOVED', [requestor_email]),)

                linked_course.save()

            else:
                return render(request, 'courses/status.html', {'formset': formset, 
                                                               'user_requested_courses': user_requested_courses})

        # Prepare all the emails for sending. all_messages must be in the format (message1, message2, ...)
        all_messages = ()
        # Iterate through all instructors
        for recipient in email_recipients.keys():
            # Iterate through all messages to a specific instructor
            for message in email_recipients[recipient]:
                all_messages = all_messages + (message,)

        send_mass_mail(all_messages, fail_silently=False)

        return HttpResponseRedirect('/status/')


def update_my_metas(request):
	# SHIBBOLETH USE
    # username = request.META['cn']  # 'cn' could also be replaced with 'REMOTE_USER'

    username = 'sean_s'  # FOR TESTING ONLY
    user_meta_courses = BbMetaCourses.objects.filter(instructor_id=username).values('pk1',
                                                                                    'meta_course_name')
    # create_add_link_form is a function wrapping the AddLinkedCoursesForm class; this is done to limit the meta course
    # choices the user can select, i.e. displaying only the user's meta courses instead of every meta course.
    add_link_form = create_add_link_form(username)
    add_link_formset_cls = formset_factory(add_link_form)

    if request.method == 'GET':
        remove_link_formset = RemoveMetaLinkedCoursesFormset(queryset=BbMetaLinkedCourses.objects.filter(row_status=0)
                                                             .filter(requestor=username), prefix='remove_link_formset')
        add_link_formset = add_link_formset_cls(prefix='add_link_formset')
        context = {'remove_link_formset': remove_link_formset,
                   'user_meta_courses': user_meta_courses,
                   'add_link_formset': add_link_formset}

        return render(request, 'courses/my_meta_courses.html', context)

    if request.method == 'POST':
        remove_link_formset = RemoveMetaLinkedCoursesFormset(request.POST, prefix='remove_link_formset')
        add_link_formset = add_link_formset_cls(request.POST, prefix='add_link_formset')
        for form in remove_link_formset:
            if form.is_valid():
                # If the to_remove checkbox field is checked, form.cleaned_data['to_remove'] will equal True
                if form.cleaned_data['to_remove']:
                    linked_course = form.save(commit=False)
                    linked_course.row_status = 2  # Disable the linked course
                    linked_course.save()
            else:
                return render(request, 'courses/my_meta_courses.html', {'remove_link_formset': remove_link_formset,
                                                                        'add_link_formset': add_link_formset,
                                                                        'user_meta_courses': user_meta_courses})

        email_recipients = {}  # Add instructor usernames as keys to this dict.
        email_subject = '[BB Meta Courses] New Request for Approval'
        email_message = 'An instructor has requested to use one of your courses in a Meta Course. ' \
                        + 'Please visit [URL REMOVED FROM PUBLIC CODE] to approve or deny this request. ' \
                        + 'If you have any questions or concerns, please contact the IT@UC Help Desk by ' \
                        + 'telephone at 513-556-HELP (4357) or by email at helpdesk@uc.edu.'

        for form in add_link_formset:
            if form.is_valid():

                child_instructor = InstructorCourses.objects.filter(course_id=form.cleaned_data['child_course'])\
                                                            .values('instructor_username')
                if child_instructor:
                    course_link = form.save(commit=False)
                    course_link.requestor = username
                    course_link.child_course_instructor = child_instructor[0]['instructor_username']
                    if course_link.child_course_instructor == course_link.requestor:
                        course_link.row_status = 0  # Enabled
                    else:
                        course_link.row_status = 1  # Pending

                        # Create email message that will be sent to instructors
                        foreign_instructor = course_link.child_course_instructor
                        if foreign_instructor not in email_recipients.keys():
                            # If the foreign_instructor isn't already a key in email_recipients,
                            #  add it along with its message.
                            foreign_instructor_email = foreign_instructor + '@ucmail.uc.edu'
                            # All messages must be in the format (subject, message, from_email, recipient_list)
                            email_recipients[foreign_instructor] = (email_subject, email_message, 'EMAIL REMOVED',
                                                                    [foreign_instructor_email])

                    course_link.save()

            else:
                return render(request, 'courses/my_meta_courses.html', {'remove_link_formset': remove_link_formset,
                                                                        'add_link_formset': add_link_formset,
                                                                        'user_meta_courses': user_meta_courses})

        # Prepare all the emails for sending. all_messages must be in the format (message1, message2, ...)
        all_messages = ()
        for recipient in email_recipients.keys():
            all_messages = all_messages + (email_recipients[recipient],)

        # send_mass_mail(all_messages, fail_silently=False)

        return HttpResponseRedirect('/metacourses/')
