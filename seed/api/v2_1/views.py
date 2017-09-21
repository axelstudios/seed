# !/usr/bin/env python
# encoding: utf-8
"""
:copyright (c) 2014 - 2017, The Regents of the University of California,
through Lawrence Berkeley National Laboratory (subject to receipt of any
required approvals from the U.S. Department of Energy) and contributors.
All rights reserved.  # NOQA
:author
"""

from django.db.models import Q
from django.http import JsonResponse
from django_filters import CharFilter, DateFilter
from django_filters.rest_framework import FilterSet
from rest_framework.decorators import detail_route
from rest_framework import status

from seed.models import (
    PropertyView,
    PropertyState,
    BuildingFile,
    Cycle
)
from seed.serializers.properties import (
    PropertyViewAsStateSerializer,
)
from seed.utils.viewsets import (
    SEEDOrgReadOnlyModelViewSet
)


class PropertyViewFilterSet(FilterSet):
    """
    Advanced filtering for PropertyView sets version 2.1.
    """
    address_line_1 = CharFilter(name="state__address_line_1", lookup_expr='contains')
    analysis_state = CharFilter(method='analysis_state_filter')
    identifier = CharFilter(method='identifier_filter')
    cycle_start = DateFilter(name='cycle__start', lookup_expr='lte')
    cycle_end = DateFilter(name='cycle__end', lookup_expr='gte')

    class Meta:
        model = PropertyView
        fields = ['identifier', 'address_line_1', 'cycle', 'property', 'cycle_start', 'cycle_end',
                  'analysis_state']

    def identifier_filter(self, queryset, name, value):
        address_line_1 = Q(state__address_line_1__icontains=value)
        jurisdiction_property_id = Q(state__jurisdiction_property_id__icontains=value)
        custom_id_1 = Q(state__custom_id_1__icontains=value)
        pm_property_id = Q(state__pm_property_id__icontains=value)

        query = (
            address_line_1 |
            jurisdiction_property_id |
            custom_id_1 |
            pm_property_id
        )
        return queryset.filter(query).order_by('-state__id')

    def analysis_state_filter(self, queryset, name, value):
        # For some reason a ChoiceFilter doesn't work on this object. I wanted to have it
        # magically look up the map from the analysis_state string to the analysis_state ID, but
        # it isn't working. Forcing it manually.

        # If the user puts in a bogus filter, then it will return All, for now

        state_id = None
        for state in PropertyState.ANALYSIS_STATE_TYPES:
            if state[1].upper() == value.upper():
                state_id = state[0]
                break

        if state_id is not None:
            return queryset.filter(Q(state__analysis_state__exact=state_id)).order_by('-state__id')
        else:
            return queryset.order_by('-state__id')


class PropertyViewSetV21(SEEDOrgReadOnlyModelViewSet):
    """
    Properties API Endpoint

        Returns::
            {
                'status': 'success',
                'properties': [
                    {
                        'id': Property primary key,
                        'campus': property is a campus,
                        'parent_property': dict of associated parent property
                        'labels': list of associated label ids
                    }
                ]
            }


    retrieve:
        Return a Property instance by pk if it is within specified org.

    list:
        Return all Properties available to user through specified org.
    """
    serializer_class = PropertyViewAsStateSerializer
    model = PropertyView
    data_name = "properties"
    filter_class = PropertyViewFilterSet
    orgfilter = 'property__organization_id'

    # Can't figure out how to do the ordering filter, so brute forcing it now with get_queryset
    # filter_backends = (DjangoFilterBackend, OrderingFilter,)
    # queryset = PropertyView.objects.all()
    # ordering = ('-id', '-state__id',)

    def get_queryset(self):
        org_id = self.get_organization(self.request)
        return PropertyView.objects.filter(property__organization_id=org_id).order_by('-state__id')

    @detail_route(methods=['GET'])
    def building_sync(self, request, pk):
        """
        Return BuildingSync representation of the property
        ---

        """
        return JsonResponse(
            {"status": "error", "message": "Not yet implemented. PK was {}".format(pk)})

    @detail_route(methods=['PUT'])
    def update_with_building_sync(self, request, pk):
        """
        Does not work in Swagger!

        Update an existing PropertyView with a building file. Currently only supports BuildingSync.
        ---
        consumes:
            - multipart/form-data
        parameters:
            - name: pk
              description: The PropertyView to update with this buildingsync file
              type: path
              required: true
            - name: organization_id
              type: integer
              required: true
            - name: cycle_id
              type: integer
              required: true
            - name: file_type
              type: string
              enum: ["Unknown", "BuildingSync", "GeoJSON"]
              required: true
            - name: file
              description: In-memory file object
              required: true
              type: file
        """
        if len(request.FILES) == 0:
            return JsonResponse({
                'success': False,
                'message': "Must pass file in as a Multipart/Form post"
            })

        the_file = request.data['file']
        file_type = BuildingFile.str_to_file_type(request.data.get('file_type', 'Unknown'))
        organization_id = request.data['organization_id']
        cycle = request.data.get('cycle_id', None)

        if not cycle:
            return JsonResponse({
                'success': False,
                'message': "Cycle ID is not defined"
            })
        else:
            cycle = Cycle.objects.get(pk=cycle)

        building_file = BuildingFile.objects.create(
            file=the_file,
            filename=the_file.name,
            file_type=file_type,
        )

        try:
            # do I need to pass cycle ID to get a specific cycle time?
            # and do I need to pass org ID to ensure orgs match?
            property_view = PropertyView.objects.get(pk=pk)
        except PropertyView.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': 'Cannot match a PropertyView with pk=%s; cycle_id=%s' % (pk, cycle)
            })

        # here, instead of relying on BuildingFile.process to create a PropertyView,
        # I'd like to either:
        #   pass in the existing property_view and have it to the assignment inside process, or
        #   just have the process() function only do the processing, and not also the PV creation, then I can do
        #   the assignment here
        p_status, property_view, messages = building_file.process(organization_id, cycle)

        if p_status:
            return JsonResponse({
                "status": "success",
                "message": "successfully imported file",
                "data": {
                    "property_view": PropertyViewAsStateSerializer(property_view).data,
                },
            })
        else:
            return JsonResponse({
                "status": "error",
                "message": "Could not process building file with messages {}".format(messages)
            }, status=status.HTTP_400_BAD_REQUEST)

