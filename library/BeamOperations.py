""" Perform beam operations on Raystation plans
    
    rename_beams:
    Automatically label beams in Raystation according to UW Standard

    Determines the primary site of the Beam set by prompting the user
    The user identifies the site using the 4 letter pre-fix from the plan name
    If the user supplies more than 4 chars, the name is cropped
    The script will test the orientation of the patient and rename the beams accordingly
    If the beamset contains a couch kick the beams are named using the gXXCyy convention
    
    Versions: 
    01.00.00 Original submission
    01.00.01 PH reviewed, suggested eliminating an unused variable, changing integer
             floating point comparison, and embedding set-up beam creation as a 
             "try" to prevent a script failure if set-up beams were not selected
    01.00.02 PH Reviewed, correct FFP positioning issue.  Changed Beamset failure to 
             load to read the same as other IO-Faults
    01.00.03 RAB Modified for new naming convention on plans and to add support for the
             field descriptions to be used for billing.
    01.00.04 RAB Modified to include isocenter renaming.
    01.00.05 RAB Modified to automatically add the 4th set-up field and clean up creation
    01.00.06 RAB Modified to round the gantry and couch angle first then convert to integer

    Known Issues:

    Multi-isocenter treatment will be incorrect in the naming conventions for set up
    fields. The script will rename the first four fields regardless of which isocenter
    to which they belong.

    This program is free software: you can redistribute it and/or modify it under
    the terms of the GNU General Public License as published by the Free Software
    Foundation, either version 3 of the License, or (at your option) any later version.
    
    This program is distributed in the hope that it will be useful, but WITHOUT
    ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
    FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
    
    You should have received a copy of the GNU General Public License along with
    this program. If not, see <http://www.gnu.org/licenses/>.
    """

__author__ = 'Adam Bayliss'
__contact__ = 'rabayliss@wisc.edu'
__date__ = '2018-09-05'

__version__ = '1.0.4'
__status__ = 'Production'
__deprecated__ = False
__reviewer__ = 'Adam Bayliss'

__reviewed__ = '2018-Sep-05'
__raystation__ = '7.0.0.19'
__maintainer__ = 'Adam Bayliss'

__email__ = 'rabayliss@wisc.edu'
__license__ = 'GPLv3'
__copyright__ = 'Copyright (C) 2018, University of Wisconsin Board of Regents'

import math
import numpy as np
import logging
import sys
import clr
import connect
import UserInterface
import StructureOperations
import PlanOperations
import Beams

clr.AddReference('System')


class Beam(object):

    def __init__(self):
        self.number = None
        self.technique = None
        self.name = None
        self.energy = None
        self.gantry_start_angle = None
        self.gantry_stop_angle = None
        self.rotation_dir = None
        self.collimator_angle = None
        self.iso = {}
        self.couch_angle = None
        self.dsp = None

    def __eq__(self, other):
        return other and \
               self.iso == other.iso \
               and self.gantry_start_angle == other.gantry_start_angle \
               and self.gantry_stop_angle == other.gantry_stop_angle \
               and self.energy == other.energy \
               and self.dsp == other.dsp \
               and self.couch_angle == other.couch_angle \
               and self.collimator_angle == other.collimator_angle \
               and self.rotation_dir == other.rotation_dir \
               and self.technique == other.technique

    def __hash__(self):
        return hash((
            frozenset(self.iso.items()),
            self.gantry_start_angle,
            self.gantry_stop_angle,
            self.energy,
            self.dsp,
            self.couch_angle,
        ))


class BeamSet(object):

    def __init__(self):
        self.name = None
        self.DicomName = None
        self.iso = {}
        self.number_of_fractions = None
        self.total_dose = None
        self.machine = None
        self.modality = None
        self.technique = None
        self.rx_target = None
        self.iso_target = None
        self.protocol_name = None
        self.origin_file = None
        self.origin_folder = None

    def __eq__(self, other):
        return other and self.iso == other.iso and self.number_of_fractions \
               == other.number_of_fractions and self.total_dose == other.total_dose \
               and self.machine == other.machine and self.modality == other.modality \
               and self.technique == other.technique and self.rx_target == other.rx_target

    def __hash__(self):
        return hash((
            frozenset(self.iso.items()),
            self.number_of_fractions,
            self.total_dose,
            self.machine,
            self.modality,
            self.technique,
        ))


class DSP(object):

    def __init__(self):
        self.name = None
        self.coords = {}

    def __eq__(self, other):
        return other and self.coords == other.coords

    def __hash__(self):
        return hash(frozenset(self.coords.items()))


# Return a patient position in the expected format for beamset definition
def patient_position_map(exam_position):
    if exam_position == 'HFP':
        return 'HeadFirstProne'
    elif exam_position == 'HFS':
        return 'HeadFirstSupine'
    elif exam_position == 'FFP':
        return 'FeetFirstProne'
    elif exam_position == 'FFS':
        return 'FeetFirstSupine'
    elif exam_position == 'HFDL':
        return 'HeadFirstDecubitusLeft'
    elif exam_position == 'HFDR':
        return 'HeadFirstDecubitusRight'
    elif exam_position == 'FFDL':
        return 'FeetFirstDecubitusLeft'
    elif exam_position == 'FFDR':
        return 'FeetFirstDecubitusRight'


def beamset_dialog(case, filename=None, path=None, order_name=None):
    """
    Ask user for information required to load a beamset including the desired protocol beamset to load.

    :param case: current case from RS
    :param folder: folder name of the location of the protocol files
    :param filename: filename housing the order
    :param order_name: optional specification of the order to use
    :return: dialog_beamset: an object of type BeamSet with values set by the user dialog
    """
    # Define an empty BeamSet object that will be the returned object
    dialog_beamset = BeamSet()
    # TODO: Uncomment in version 9 to load the available machine inputs from current commissioned list
    # machine_db = connect.get_current('MachineDB')
    # machines = machine_db.QueryCommissionedMachineInfo(Filter={})
    # machine_list = []
    # for i, m in enumerate(machines):
    #     if m['IsCommissioned']:
    #         machine_list.append(m['Name'])
    # TODO Test gating option
    # TODO Load all available beamsets found in a file
    available_modality = ['Photons', 'Electrons']
    available_technique = ['Conformal', 'SMLC', 'VMAT', 'DMLC', 'ConformalArc', 'TomoHelical', 'TomoDirect']
    machine_list = ['TrueBeam', 'TrueBeamSTx']

    # Open the user supplied filename located at folder and return a list of available beamsets
    # Should be able to eliminate this if after the modifications to select_element are complete
    if filename is not None:
        dialog_beamset.origin_file = filename
        dialog_beamset.origin_folder = path
        logging.debug('looking in {} at {} for a {}'.format(filename, path, 'beamset'))
        available_beamsets = Beams.select_element(
            set_level='beamset',
            set_type=None,
            set_elements='beam',
            filename=filename,
            dialog=False,
            folder=path,
            verbose_logging=False)

    targets = StructureOperations.find_targets(case=case)

    dialog = UserInterface.InputDialog(
        inputs={
            '0': 'Choose the Rx target',
            '1': 'Enter the Beamset Name, typically <Site>_VMA_R0A0',
            '2': 'Enter the number of fractions',
            '3': 'Enter total dose in cGy',
            '4': 'Choose Treatment Machine',
            '6': 'Choose a Technique',
            '7': 'Choose a Target for Isocenter Placement',
            '8': 'Choose a Beamset to load'
        },
        title='Beamset Inputs',
        datatype={
            '0': 'combo',
            '4': 'combo',
            '6': 'combo',
            '7': 'combo',
            '8': 'combo'
        },
        initial={
            '1': 'XXXX_VMA_R0A0',
            '4': 'VMAT',
            '8': available_beamsets[0]
        },
        options={
            '0': targets,
            '4': machine_list,
            '6': available_technique,
            '7': targets,
            '8': available_beamsets
        },
        required=['0',
                  '2',
                  '3',
                  '4',
                  '6',
                  '7',
                  '8'])

    # Launch the dialog
    response = dialog.show()
    if response == {}:
        sys.exit('Beamset loading was cancelled')

    dialog_beamset.rx_target = dialog.values['0']
    dialog_beamset.name = dialog.values['1']
    dialog_beamset.DicomName = dialog.values['1']
    dialog_beamset.number_of_fractions = float(dialog.values['2'])
    dialog_beamset.total_dose = float(dialog.values['3'])
    dialog_beamset.machine = dialog.values['4']
    dialog_beamset.modality = 'Photons'
    dialog_beamset.technique = dialog.values['6']
    dialog_beamset.iso_target = dialog.values['7']
    dialog_beamset.protocol_name = dialog.values['8']

    return dialog_beamset


def find_isocenter_parameters(case, exam, beamset, iso_target):
    """Function to return the dict object needed for isocenter placement from the center of a supplied
    name of a structure"""

    try:
        isocenter_position = case.PatientModel.StructureSets[exam.Name]. \
            RoiGeometries[iso_target].GetCenterOfRoi()
    except Exception:
        logging.warning('Aborting, could not locate center of {}'.format(iso_target))
        sys.exit('Failed to place isocenter')

    # Place isocenter
    # TODO Add a check on laterality at this point (if -7< x < 7 ) put out a warning
    ptv_center = {'x': isocenter_position.x,
                  'y': isocenter_position.y,
                  'z': isocenter_position.z}
    isocenter_parameters = beamset.CreateDefaultIsocenterData(Position=ptv_center)
    isocenter_parameters['Name'] = "iso_" + beamset.DicomPlanLabel
    isocenter_parameters['NameOfIsocenterToRef'] = "iso_" + beamset.DicomPlanLabel
    logging.info('Isocenter chosen based on center of {}.'.format(iso_target) +
                 'Parameters are: x={}, y={}:, z={}, assigned to isocenter name{}'.format(
                     ptv_center['x'],
                     ptv_center['y'],
                     ptv_center['z'],
                     isocenter_parameters['Name']))

    return isocenter_parameters


def create_beamset(patient, case, exam, plan,
                   BeamSet=None,
                   dialog=True,
                   filename=None,
                   path=None,
                   order_name=None):
    """ Create a beamset by opening a dialog with user or loading from scratch
    Currently relies on finding out information via a dialog. I would like it to optionally take the elements
    from the BeamSet class and return the result

    Running as a dialog:
    BeamOperations.create_beamset(patient=patient, case=case, exam=exam, plan=plan, dialog=True)

    Running using the BeamSet class

       """
    if dialog:
        b = beamset_dialog(case=case, filename=filename, path=path, order_name=order_name)
    elif BeamSet is not None:
        b = BeamSet
    else:
        logging.warning('Cannot load beamset due to incorrect argument list')

    plan.AddNewBeamSet(
        Name=b.DicomName,
        ExaminationName=exam.Name,
        MachineName=b.machine,
        Modality=b.modality,
        TreatmentTechnique=b.technique,
        PatientPosition=patient_position_map(exam.PatientPosition),
        NumberOfFractions=b.number_of_fractions,
        CreateSetupBeams=True,
        UseLocalizationPointAsSetupIsocenter=False,
        Comment="",
        RbeModelReference=None,
        EnableDynamicTrackingForVero=False,
        NewDoseSpecificationPointNames=[],
        NewDoseSpecificationPoints=[],
        RespiratoryMotionCompensationTechnique="Disabled",
        RespiratorySignalSource="Disabled")

    beamset = plan.BeamSets[b.DicomName]
    patient.Save()

    try:
        beamset.AddDosePrescriptionToRoi(RoiName=b.rx_target,
                                         DoseVolume=80,
                                         PrescriptionType='DoseAtVolume',
                                         DoseValue=b.total_dose,
                                         RelativePrescriptionLevel=1,
                                         AutoScaleDose=True)
    except Exception:
        logging.warning('Unable to set prescription')
    return beamset


def place_beams_in_beamset(iso, beamset, beams):
    """
    Put beams in place based on a list of Beam objects
    :param iso: isocenter data dictionary
    :param beamset: beamset to which to add beams
    :param beams: list of Beam objects
    :return:
    """
    for b in beams:
        logging.info(('Loading Beam {}. Type {}, Name {}, Energy {}, StartAngle {}, StopAngle {}, ' +
                      'RotationDirection {}, CollimatorAngle {}, CouchAngle {} ').format(
            b.number, b.technique, b.name,
            b.energy, b.gantry_start_angle,
            b.gantry_stop_angle, b.rotation_dir,
            b.collimator_angle, b.couch_angle))

        beamset.CreateArcBeam(ArcStopGantryAngle=b.gantry_stop_angle,
                              ArcRotationDirection=b.rotation_dir,
                              Energy=b.energy,
                              IsocenterData=iso,
                              Name=b.name,
                              Description=b.name,
                              GantryAngle=b.gantry_start_angle,
                              CouchAngle=b.couch_angle,
                              CollimatorAngle=b.collimator_angle)


def rename_beams():
    # These are the techniques associated with billing codes in the clinic
    # they will be imported
    available_techniques = [
        'Static MLC -- 2D',
        'Static NoMLC -- 2D',
        'Electron -- 2D',
        'Static MLC -- 3D',
        'Static NoMLC -- 3D',
        'Electron -- 3D',
        'FiF MLC -- 3D',
        'Static PRDR MLC -- 3D',
        'SnS MLC -- IMRT',
        'SnS PRDR MLC -- IMRT',
        'Conformal Arc -- 2D',
        'Conformal Arc -- 3D',
        'VMAT Arc -- IMRT',
        'Tomo Helical -- IMRT']
    supported_rs_techniques = [
        'SMLC',
        'DynamicArc',
        'TomoHelical']

    try:
        patient = connect.get_current('Patient')
        case = connect.get_current('Case')
        exam = connect.get_current('Examination')
        plan = connect.get_current('Plan')
        beamset = connect.get_current("BeamSet")

    except Exception:
        UserInterface.WarningBox('This script requires a Beam Set to be loaded')
        sys.exit('This script requires a Beam Set to be loaded')

    initial_sitename = beamset.DicomPlanLabel[:4]
    # Prompt the user for Site Name and Billing technique
    dialog = UserInterface.InputDialog(inputs={'Site': 'Enter a Site name, e.g. BreL',
                                               'Technique': 'Select Treatment Technique (Billing)'},
                                       datatype={'Technique': 'combo'},
                                       initial={'Technique': 'Select',
                                                'Site': initial_sitename},
                                       options={'Technique': available_techniques},
                                       required=['Site', 'Technique'])
    # Show the dialog
    print
    dialog.show()

    site_name = dialog.values['Site']
    input_technique = dialog.values['Technique']
    #
    # Electrons, 3D, and VMAT Arcs are all that are supported.  Reject plans that aren't
    technique = beamset.DeliveryTechnique
    #
    # Oddly enough, Electrons are DeliveryTechnique = 'SMLC'
    if technique not in supported_rs_techniques:
        logging.warning('Technique: {} unsupported in renaming script'.format(technique))
        raise IOError("Technique unsupported, manually name beams according to clinical convention.")

    # Tomo Helical naming
    if technique == 'TomoHelical':
        for b in beamset.Beams:
            beam_description = 'TomoHelical' + site_name
            b.Name = beam_description
            b.Description = input_technique
        return

    # While loop variable definitions
    beam_index = 0
    patient_position = beamset.PatientPosition
    # Turn on set-up fields
    beamset.PatientSetup.UseSetupBeams = True
    logging.debug('Renaming and adding set up fields to Beam Set with name {}, patient position {}, technique {}'.
                  format(beamset.DicomPlanLabel, beamset.PatientPosition, beamset.DeliveryTechnique))
    # Rename isocenters
    for b in beamset.Beams:
        iso_n = int(b.Isocenter.IsocenterNumber)
        b.Isocenter.Annotation.Name = 'Iso_' + beamset.DicomPlanLabel + '_' + str(iso_n + 1)
    #
    # HFS
    if patient_position == 'HeadFirstSupine':
        standard_beam_name = 'Naming Error'
        for b in beamset.Beams:
            try:
                gantry_angle = round(float(b.GantryAngle), 1)
                couch_angle = round(float(b.CouchAngle), 1)
                gantry_angle_string = str(int(gantry_angle))
                couch_angle_string = str(int(couch_angle))
                # 
                # Determine if the type is an Arc or SMLC
                # Name arcs as #_Arc_<Site>_<Direction>_<Couch>
                if technique == 'DynamicArc':
                    arc_direction = b.ArcRotationDirection
                    if arc_direction == 'Clockwise':
                        arc_direction_string = 'CW'
                    else:
                        arc_direction_string = 'CCW'

                    # Based on convention for billing, e.g. "1 CCW VMAT -- IMRT"
                    # set the beam_description
                    beam_description = (str(beam_index + 1) + ' ' + arc_direction_string +
                                        ' ' + input_technique)
                    if couch_angle == 0:
                        standard_beam_name = (str(beam_index + 1) + '_' + site_name + '_Arc')
                    else:
                        standard_beam_name = (str(beam_index + 1) + '_' + site_name + '_Arc'
                                              + '_c' + couch_angle_string.zfill(3))
                else:
                    # Based on convention for billing, e.g. "1 SnS PRDR MLC -- IMRT"
                    # set the beam_description
                    beam_description = str(beam_index + 1) + ' ' + input_technique
                    if couch_angle != 0:
                        standard_beam_name = (str(beam_index + 1) + '_' + site_name
                                              + '_g' + gantry_angle_string.zfill(3)
                                              + 'c' + couch_angle_string.zfill(3))
                    elif gantry_angle == 180:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_PA'
                    elif 180 < gantry_angle < 270:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_RPO'
                    elif gantry_angle == 270:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_RLAT'
                    elif 270 < gantry_angle < 360:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_RAO'
                    elif gantry_angle == 0:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_AP'
                    elif 0 < gantry_angle < 90:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_LAO'
                    elif gantry_angle == 90:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_LLAT'
                    elif 90 < gantry_angle < 180:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_LPO'

                # Set the beamset names and description according to the convention above
                b.Name = standard_beam_name
                b.Description = beam_description
                beam_index += 1
            except Exception:
                logging.warning('Error occurred in setting names of beams')
                UserInterface.WarningBox('Error occurred in setting names of beams')
                sys.exit('Error occurred in setting names of beams')

        # Set-Up Fields
        # HFS Setup
        # set_up: [ Set-Up Field Name, Set-Up Field Description, Gantry Angle, Dose Rate]
        set_up = {0: ['SetUp AP', 'SetUp AP', 0.0, '5'],
                  1: ['SetUp RtLat', 'SetUp RtLat', 270.0, '5'],
                  2: ['SetUp LtLat', 'SetUp LtLat', 90.0, '5'],
                  3: ['SetUp CBCT', 'SetUp CBCT', 0.0, '5']
                  }
        # Extract the angles
        angles = []
        for k, v in set_up.iteritems():
            angles.append(v[2])
            print
            "v2={}".format(v[2])

        beamset.UpdateSetupBeams(ResetSetupBeams=True,
                                 SetupBeamsGantryAngles=angles)

        # Set the set-up parameter specifics
        for i, b in enumerate(beamset.PatientSetup.SetupBeams):
            b.Name = set_up[i][0]
            b.Description = set_up[i][1]
            b.GantryAngle = str(set_up[i][2])
            b.Segments[0].DoseRate = set_up[i][3]
    # HFLDR
    elif patient_position == 'HeadFirstDecubitusRight':
        standard_beam_name = 'Naming Error'
        for b in beamset.Beams:
            try:
                gantry_angle = round(float(b.GantryAngle), 1)
                couch_angle = round(float(b.CouchAngle), 1)
                gantry_angle_string = str(int(gantry_angle))
                couch_angle_string = str(int(couch_angle))
                #
                # Determine if the type is an Arc or SMLC
                # Name arcs as #_Arc_<Site>_<Direction>_<Couch>
                if technique == 'DynamicArc':
                    arc_direction = b.ArcRotationDirection
                    if arc_direction == 'Clockwise':
                        arc_direction_string = 'CW'
                    else:
                        arc_direction_string = 'CCW'

                    # Based on convention for billing, e.g. "1 CCW VMAT -- IMRT"
                    # set the beam_description
                    beam_description = (str(beam_index + 1) + ' ' + arc_direction_string +
                                        ' ' + input_technique)
                    if couch_angle == 0:
                        standard_beam_name = (str(beam_index + 1) + '_' + site_name + '_Arc')
                    else:
                        standard_beam_name = (str(beam_index + 1) + '_' + site_name + '_Arc'
                                              + '_c' + couch_angle_string.zfill(3))
                else:
                    # Based on convention for billing, e.g. "1 SnS PRDR MLC -- IMRT"
                    # set the beam_description
                    beam_description = str(beam_index + 1) + ' ' + input_technique
                    if couch_angle != 0:
                        standard_beam_name = (str(beam_index + 1) + '_' + site_name
                                              + '_g' + gantry_angle_string.zfill(3)
                                              + 'c' + couch_angle_string.zfill(3))
                    elif gantry_angle == 180:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_RLAT'
                    elif 180 < gantry_angle < 270:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_RAO'
                    elif gantry_angle == 270:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_AP'
                    elif 270 < gantry_angle < 360:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_LAO'
                    elif gantry_angle == 0:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_LLAT'
                    elif 0 < gantry_angle < 90:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_LPO'
                    elif gantry_angle == 90:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_PA'
                    elif 90 < gantry_angle < 180:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_LPO'

                # Set the beamset names and description according to the convention above
                b.Name = standard_beam_name
                b.Description = beam_description
                beam_index += 1
            except Exception:
                logging.warning('Error occurred in setting names of beams')
                UserInterface.WarningBox('Error occurred in setting names of beams')
                sys.exit('Error occurred in setting names of beams')

        # Set-Up Fields
        # HFLDR Setup
        # set_up: [ Set-Up Field Name, Set-Up Field Description, Gantry Angle, Dose Rate]
        set_up = {0: ['SetUp LtLat', 'SetUp LtLat', 0.0, '5'],
                  1: ['SetUp AP', 'SetUp AP', 270.0, '5'],
                  2: ['SetUp PA', 'SetUp PA', 90.0, '5'],
                  3: ['SetUp CBCT', 'SetUp CBCT', 0.0, '5']
                  }
        # Extract the angles
        angles = []
        for k, v in set_up.iteritems():
            angles.append(v[2])
            print
            "v2={}".format(v[2])

        beamset.UpdateSetupBeams(ResetSetupBeams=True,
                                 SetupBeamsGantryAngles=angles)

        # Set the set-up parameter specifics
        for i, b in enumerate(beamset.PatientSetup.SetupBeams):
            b.Name = set_up[i][0]
            b.Description = set_up[i][1]
            b.GantryAngle = str(set_up[i][2])
            b.Segments[0].DoseRate = set_up[i][3]
    # HFLDL
    elif patient_position == 'HeadFirstDecubitusLeft':
        standard_beam_name = 'Naming Error'
        for b in beamset.Beams:
            try:
                gantry_angle = round(float(b.GantryAngle), 1)
                couch_angle = round(float(b.CouchAngle), 1)
                gantry_angle_string = str(int(gantry_angle))
                couch_angle_string = str(int(couch_angle))
                #
                # Determine if the type is an Arc or SMLC
                # Name arcs as #_Arc_<Site>_<Direction>_<Couch>
                if technique == 'DynamicArc':
                    arc_direction = b.ArcRotationDirection
                    if arc_direction == 'Clockwise':
                        arc_direction_string = 'CW'
                    else:
                        arc_direction_string = 'CCW'

                    # Based on convention for billing, e.g. "1 CCW VMAT -- IMRT"
                    # set the beam_description
                    beam_description = (str(beam_index + 1) + ' ' + arc_direction_string +
                                        ' ' + input_technique)
                    if couch_angle == 0:
                        standard_beam_name = (str(beam_index + 1) + '_' + site_name + '_Arc')
                    else:
                        standard_beam_name = (str(beam_index + 1) + '_' + site_name + '_Arc'
                                              + '_c' + couch_angle_string.zfill(3))
                else:
                    # Based on convention for billing, e.g. "1 SnS PRDR MLC -- IMRT"
                    # set the beam_description
                    beam_description = str(beam_index + 1) + ' ' + input_technique
                    if couch_angle != 0:
                        standard_beam_name = (str(beam_index + 1) + '_' + site_name
                                              + '_g' + gantry_angle_string.zfill(3)
                                              + 'c' + couch_angle_string.zfill(3))
                    elif gantry_angle == 180:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_LLAT'
                    elif 180 < gantry_angle < 270:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_LPO'
                    elif gantry_angle == 270:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_PA'
                    elif 270 < gantry_angle < 360:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_RPO'
                    elif gantry_angle == 0:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_RLAT'
                    elif 0 < gantry_angle < 90:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_RAO'
                    elif gantry_angle == 90:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_AP'
                    elif 90 < gantry_angle < 180:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_LAO'

                # Set the beamset names and description according to the convention above
                b.Name = standard_beam_name
                b.Description = beam_description
                beam_index += 1
            except Exception:
                logging.warning('Error occurred in setting names of beams')
                UserInterface.WarningBox('Error occurred in setting names of beams')
                sys.exit('Error occurred in setting names of beams')

        # Set-Up Fields
        # HFLDL Setup
        # set_up: [ Set-Up Field Name, Set-Up Field Description, Gantry Angle, Dose Rate]
        set_up = {0: ['SetUp RtLat', 'SetUp RtLat', 0.0, '5'],
                  1: ['SetUp PA', 'SetUp PA', 270.0, '5'],
                  2: ['SetUp AP', 'SetUp AP', 90.0, '5'],
                  3: ['SetUp CBCT', 'SetUp CBCT', 0.0, '5']
                  }
        # Extract the angles
        angles = []
        for k, v in set_up.iteritems():
            angles.append(v[2])
            print
            "v2={}".format(v[2])

        beamset.UpdateSetupBeams(ResetSetupBeams=True,
                                 SetupBeamsGantryAngles=angles)

        # Set the set-up parameter specifics
        for i, b in enumerate(beamset.PatientSetup.SetupBeams):
            b.Name = set_up[i][0]
            b.Description = set_up[i][1]
            b.GantryAngle = str(set_up[i][2])
            b.Segments[0].DoseRate = set_up[i][3]
    # HFP
    elif patient_position == 'HeadFirstProne':
        standard_beam_name = 'Naming Error'
        for b in beamset.Beams:
            try:
                gantry_angle = round(float(b.GantryAngle), 1)
                couch_angle = round(float(b.CouchAngle), 1)
                gantry_angle_string = str(int(gantry_angle))
                couch_angle_string = str(int(couch_angle))
                #
                # Determine if the type is an Arc or SMLC
                # Name arcs as #_Arc_<Site>_<Direction>_<Couch>
                if technique == 'DynamicArc':
                    arc_direction = b.ArcRotationDirection
                    if arc_direction == 'Clockwise':
                        arc_direction_string = 'CW'
                    else:
                        arc_direction_string = 'CCW'

                    # Based on convention for billing, e.g. "1 CCW VMAT -- IMRT"
                    # set the beam_description
                    beam_description = (str(beam_index + 1) + ' ' + arc_direction_string +
                                        ' ' + input_technique)
                    if couch_angle == 0:
                        standard_beam_name = (str(beam_index + 1) + '_' + site_name + '_Arc')
                    else:
                        standard_beam_name = (str(beam_index + 1) + '_' + site_name + '_Arc'
                                              + '_c' + couch_angle_string.zfill(3))
                else:
                    # Based on convention for billing, e.g. "1 SnS PRDR MLC -- IMRT"
                    # set the beam_description
                    beam_description = str(beam_index + 1) + ' ' + input_technique
                    if couch_angle != 0:
                        standard_beam_name = (str(beam_index + 1) + '_' + site_name
                                              + '_g' + gantry_angle_string.zfill(3)
                                              + 'c' + couch_angle_string.zfill(3))
                    elif gantry_angle == 180:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_AP'
                    elif 180 < gantry_angle < 270:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_LAO'
                    elif gantry_angle == 270:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_LLAT'
                    elif 270 < gantry_angle < 360:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_LPO'
                    elif gantry_angle == 0:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_PA'
                    elif 0 < gantry_angle < 90:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_RPO'
                    elif gantry_angle == 90:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_RLAT'
                    elif 90 < gantry_angle < 180:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_RAO'
                # Set the beamset names and description according to the convention above
                b.Name = standard_beam_name
                b.Description = beam_description
                beam_index += 1
            except Exception:
                UserInterface.WarningBox('Error occurred in setting names of beams')
                sys.exit('Error occurred in setting names of beams')
        #
        # Set-Up fields
        # set_up: [ Set-Up Field Name, Set-Up Field Description, Gantry Angle, Dose Rate]
        set_up = {0: ['SetUp PA', 'SetUp PA', 0, '5'],
                  1: ['SetUp RtLat', 'SetUp RtLat', 90.0, '5'],
                  2: ['SetUp LtLat', 'SetUp LtLat', 270.0, '5'],
                  3: ['SetUp CBCT', 'SetUp CBCT', 0.0, '5']
                  }
        # Extract the angles
        angles = []
        for k, v in set_up.iteritems():
            angles.append(v[2])
        beamset.UpdateSetupBeams(ResetSetupBeams=True,
                                 SetupBeamsGantryAngles=angles)

        for i, b in enumerate(beamset.PatientSetup.SetupBeams):
            b.Name = set_up[i][0]
            b.Description = set_up[i][1]
            b.GantryAngle = str(set_up[i][2])
            b.Segments[0].DoseRate = set_up[i][3]
    # FFS
    elif patient_position == 'FeetFirstSupine':
        standard_beam_name = 'Naming Error'
        for b in beamset.Beams:
            try:
                gantry_angle = round(float(b.GantryAngle), 1)
                couch_angle = round(float(b.CouchAngle), 1)
                gantry_angle_string = str(int(gantry_angle))
                couch_angle_string = str(int(couch_angle))
                #
                # Determine if the type is an Arc or SMLC
                # Name arcs as #_Arc_<Site>_<Direction>_<Couch>
                if technique == 'DynamicArc':
                    arc_direction = b.ArcRotationDirection
                    if arc_direction == 'Clockwise':
                        arc_direction_string = 'CW'
                    else:
                        arc_direction_string = 'CCW'

                    # Based on convention for billing, e.g. "1 CCW VMAT -- IMRT"
                    # set the beam_description
                    beam_description = (str(beam_index + 1) + ' ' + arc_direction_string +
                                        ' ' + input_technique)
                    if couch_angle == 0:
                        standard_beam_name = (str(beam_index + 1) + '_' + site_name + '_Arc')
                    else:
                        standard_beam_name = (str(beam_index + 1) + '_' + site_name + '_Arc'
                                              + '_c' + couch_angle_string.zfill(3))
                else:
                    # Based on convention for billing, e.g. "1 SnS PRDR MLC -- IMRT"
                    # set the beam_description
                    beam_description = str(beam_index + 1) + ' ' + input_technique
                    if couch_angle != 0:
                        standard_beam_name = (str(beam_index + 1) + '_' + site_name
                                              + '_g' + gantry_angle_string.zfill(3)
                                              + 'c' + couch_angle_string.zfill(3))
                    elif gantry_angle == 180:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_PA'
                    elif 180 < gantry_angle < 270:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_LPO'
                    elif gantry_angle == 270:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_LLAT'
                    elif 270 < gantry_angle < 360:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_LAO'
                    elif gantry_angle == 0:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_AP'
                    elif 0 < gantry_angle < 90:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_RAO'
                    elif gantry_angle == 90:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_RLAT'
                    elif 90 < gantry_angle < 180:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_RPO'
                # Set the beamset names and description according to the convention above
                b.Name = standard_beam_name
                b.Description = beam_description
                beam_index += 1
            except Exception:
                UserInterface.WarningBox('Error occured in setting names of beams')
                sys.exit('Error occurred in setting names of beams')

        # Set-Up fields
        # set_up: [ Set-Up Field Name, Set-Up Field Description, Gantry Angle, Dose Rate]
        set_up = {0: ['SetUp AP', 'SetUp AP', 0, '5'],
                  1: ['SetUp RtLat', 'SetUp RtLat', 90.0, '5'],
                  2: ['SetUp LtLat', 'SetUp LtLat', 270.0, '5'],
                  3: ['SetUp CBCT', 'SetUp CBCT', 0.0, '5']
                  }
        # Extract the angles
        angles = []
        for k, v in set_up.iteritems():
            angles.append(v[2])
        beamset.UpdateSetupBeams(ResetSetupBeams=True,
                                 SetupBeamsGantryAngles=angles)

        for i, b in enumerate(beamset.PatientSetup.SetupBeams):
            b.Name = set_up[i][0]
            b.Description = set_up[i][1]
            b.GantryAngle = str(set_up[i][2])
            b.Segments[0].DoseRate = set_up[i][3]

            # Address the Feet-first prone position
    # FFLDR
    elif patient_position == 'FeetFirstDecubitusRight':
        standard_beam_name = 'Naming Error'
        for b in beamset.Beams:
            try:
                gantry_angle = round(float(b.GantryAngle), 1)
                couch_angle = round(float(b.CouchAngle), 1)
                gantry_angle_string = str(int(gantry_angle))
                couch_angle_string = str(int(couch_angle))
                #
                # Determine if the type is an Arc or SMLC
                # Name arcs as #_Arc_<Site>_<Direction>_<Couch>
                if technique == 'DynamicArc':
                    arc_direction = b.ArcRotationDirection
                    if arc_direction == 'Clockwise':
                        arc_direction_string = 'CW'
                    else:
                        arc_direction_string = 'CCW'

                    # Based on convention for billing, e.g. "1 CCW VMAT -- IMRT"
                    # set the beam_description
                    beam_description = (str(beam_index + 1) + ' ' + arc_direction_string +
                                        ' ' + input_technique)
                    if couch_angle == 0:
                        standard_beam_name = (str(beam_index + 1) + '_' + site_name + '_Arc')
                    else:
                        standard_beam_name = (str(beam_index + 1) + '_' + site_name + '_Arc'
                                              + '_c' + couch_angle_string.zfill(3))
                else:
                    # Based on convention for billing, e.g. "1 SnS PRDR MLC -- IMRT"
                    # set the beam_description
                    beam_description = str(beam_index + 1) + ' ' + input_technique
                    if couch_angle != 0:
                        standard_beam_name = (str(beam_index + 1) + '_' + site_name
                                              + '_g' + gantry_angle_string.zfill(3)
                                              + 'c' + couch_angle_string.zfill(3))
                    elif gantry_angle == 180:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_RLAT'
                    elif 180 < gantry_angle < 270:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_RPO'
                    elif gantry_angle == 270:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_PA'
                    elif 270 < gantry_angle < 360:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_LPO'
                    elif gantry_angle == 0:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_LLAT'
                    elif 0 < gantry_angle < 90:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_LAO'
                    elif gantry_angle == 90:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_AP'
                    elif 90 < gantry_angle < 180:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_RAO'

                # Set the beamset names and description according to the convention above
                b.Name = standard_beam_name
                b.Description = beam_description
                beam_index += 1
            except Exception:
                logging.warning('Error occurred in setting names of beams')
                UserInterface.WarningBox('Error occurred in setting names of beams')
                sys.exit('Error occurred in setting names of beams')

        # Set-Up Fields
        # FFLDR Setup
        # set_up: [ Set-Up Field Name, Set-Up Field Description, Gantry Angle, Dose Rate]
        set_up = {0: ['SetUp RtLat', 'SetUp RtLat', 0.0, '5'],
                  1: ['SetUp PA', 'SetUp PA', 270.0, '5'],
                  2: ['SetUp AP', 'SetUp AP', 90.0, '5'],
                  3: ['SetUp CBCT', 'SetUp CBCT', 0.0, '5']
                  }
        # Extract the angles
        angles = []
        for k, v in set_up.iteritems():
            angles.append(v[2])
            print
            "v2={}".format(v[2])

        beamset.UpdateSetupBeams(ResetSetupBeams=True,
                                 SetupBeamsGantryAngles=angles)

        # Set the set-up parameter specifics
        for i, b in enumerate(beamset.PatientSetup.SetupBeams):
            b.Name = set_up[i][0]
            b.Description = set_up[i][1]
            b.GantryAngle = str(set_up[i][2])
            b.Segments[0].DoseRate = set_up[i][3]
    # FFLDL
    elif patient_position == 'FeetFirstDecubitusLeft':
        standard_beam_name = 'Naming Error'
        for b in beamset.Beams:
            try:
                gantry_angle = round(float(b.GantryAngle), 1)
                couch_angle = round(float(b.CouchAngle), 1)
                gantry_angle_string = str(int(gantry_angle))
                couch_angle_string = str(int(couch_angle))
                #
                # Determine if the type is an Arc or SMLC
                # Name arcs as #_Arc_<Site>_<Direction>_<Couch>
                if technique == 'DynamicArc':
                    arc_direction = b.ArcRotationDirection
                    if arc_direction == 'Clockwise':
                        arc_direction_string = 'CW'
                    else:
                        arc_direction_string = 'CCW'

                    # Based on convention for billing, e.g. "1 CCW VMAT -- IMRT"
                    # set the beam_description
                    beam_description = (str(beam_index + 1) + ' ' + arc_direction_string +
                                        ' ' + input_technique)
                    if couch_angle == 0:
                        standard_beam_name = (str(beam_index + 1) + '_' + site_name + '_Arc')
                    else:
                        standard_beam_name = (str(beam_index + 1) + '_' + site_name + '_Arc'
                                              + '_c' + couch_angle_string.zfill(3))
                else:
                    # Based on convention for billing, e.g. "1 SnS PRDR MLC -- IMRT"
                    # set the beam_description
                    beam_description = str(beam_index + 1) + ' ' + input_technique
                    if couch_angle != 0:
                        standard_beam_name = (str(beam_index + 1) + '_' + site_name
                                              + '_g' + gantry_angle_string.zfill(3)
                                              + 'c' + couch_angle_string.zfill(3))
                    elif gantry_angle == 180:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_LLAT'
                    elif 180 < gantry_angle < 270:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_LAO'
                    elif gantry_angle == 270:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_AP'
                    elif 270 < gantry_angle < 360:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_RAO'
                    elif gantry_angle == 0:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_RLAT'
                    elif 0 < gantry_angle < 90:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_RPO'
                    elif gantry_angle == 90:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_PA'
                    elif 90 < gantry_angle < 180:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_LPO'

                # Set the beamset names and description according to the convention above
                b.Name = standard_beam_name
                b.Description = beam_description
                beam_index += 1
            except Exception:
                logging.warning('Error occurred in setting names of beams')
                UserInterface.WarningBox('Error occurred in setting names of beams')
                sys.exit('Error occurred in setting names of beams')

        # Set-Up Fields
        # FFLDL Setup
        # set_up: [ Set-Up Field Name, Set-Up Field Description, Gantry Angle, Dose Rate]
        set_up = {0: ['SetUp RtLat', 'SetUp RtLat', 0.0, '5'],
                  1: ['SetUp AP', 'SetUp AP', 270.0, '5'],
                  2: ['SetUp PA', 'SetUp PA', 90.0, '5'],
                  3: ['SetUp CBCT', 'SetUp CBCT', 0.0, '5']
                  }
        # Extract the angles
        angles = []
        for k, v in set_up.iteritems():
            angles.append(v[2])
            print
            "v2={}".format(v[2])

        beamset.UpdateSetupBeams(ResetSetupBeams=True,
                                 SetupBeamsGantryAngles=angles)

        # Set the set-up parameter specifics
        for i, b in enumerate(beamset.PatientSetup.SetupBeams):
            b.Name = set_up[i][0]
            b.Description = set_up[i][1]
            b.GantryAngle = str(set_up[i][2])
            b.Segments[0].DoseRate = set_up[i][3]
    # FFP
    elif patient_position == 'FeetFirstProne':
        for b in beamset.Beams:
            standard_beam_name = 'Naming Error'
            try:
                gantry_angle = round(float(b.GantryAngle), 1)
                couch_angle = round(float(b.CouchAngle), 1)
                gantry_angle_string = str(int(gantry_angle))
                couch_angle_string = str(int(couch_angle))
                #
                # Determine if the type is an Arc or SMLC
                # Name arcs as #_Arc_<Site>_<Direction>_<Couch>
                if technique == 'DynamicArc':
                    arc_direction = b.ArcRotationDirection
                    if arc_direction == 'Clockwise':
                        arc_direction_string = 'CW'
                    else:
                        arc_direction_string = 'CCW'

                    # Based on convention for billing, e.g. "1 CCW VMAT -- IMRT"
                    # set the beam_description
                    beam_description = (str(beam_index + 1) + ' ' + arc_direction_string +
                                        ' ' + input_technique)
                    if couch_angle == 0:
                        standard_beam_name = (str(beam_index + 1) + '_' + site_name + '_Arc')
                    else:
                        standard_beam_name = (str(beam_index + 1) + '_' + site_name + '_Arc'
                                              + '_c' + couch_angle_string.zfill(3))
                else:
                    # Based on convention for billing, e.g. "1 SnS PRDR MLC -- IMRT"
                    # set the beam_description
                    beam_description = str(beam_index + 1) + ' ' + input_technique
                    if couch_angle != 0:
                        standard_beam_name = (str(beam_index + 1) + '_' + site_name
                                              + '_g' + gantry_angle_string.zfill(3)
                                              + 'c' + couch_angle_string.zfill(3))
                    elif gantry_angle == 180:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_AP'
                    elif 180 < gantry_angle < 270:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_RAO'
                    elif gantry_angle == 270:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_RLAT'
                    elif 270 < gantry_angle < 360:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_RPO'
                    elif gantry_angle == 0:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_PA'
                    elif 0 < gantry_angle < 90:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_LPO'
                    elif gantry_angle == 90:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_LLAT'
                    elif 90 < gantry_angle < 180:
                        standard_beam_name = str(beam_index + 1) + '_' + site_name + '_LAO'
                # Set the beamset names and description according to the convention above
                b.Name = standard_beam_name
                b.Description = beam_description
                beam_index += 1
            except Exception:
                UserInterface.WarningBox('Error occurred in setting names of beams')
                sys.exit('Error occurred in setting names of beams')
        # FFP: Set-Up fields
        # set_up: [ Set-Up Field Name, Set-Up Field Description, Gantry Angle, Dose Rate]
        set_up = {0: ['SetUp PA', 'SetUp PA', 0, '5'],
                  1: ['SetUp RtLat', 'SetUp RtLat', 270.0, '5'],
                  2: ['SetUp LtLat', 'SetUp LtLat', 90.0, '5'],
                  3: ['SetUp CBCT', 'SetUp CBCT', 0.0, '5']
                  }
        # Extract the angles
        angles = []
        for k, v in set_up.iteritems():
            angles.append(v[2])
        beamset.UpdateSetupBeams(ResetSetupBeams=True,
                                 SetupBeamsGantryAngles=angles)

        for i, b in enumerate(beamset.PatientSetup.SetupBeams):
            b.Name = set_up[i][0]
            b.Description = set_up[i][1]
            b.GantryAngle = str(set_up[i][2])
            b.Segments[0].DoseRate = set_up[i][3]
    else:
        raise IOError("Patient Orientation Unsupported.. Manual Beam Naming Required")


def find_dsp(plan, beam_set, dose_per_fraction=None, Beam=None):
    """
    :param plan: current plan
    :param beam_set: current beamset
    :param dose_per_fraction: dose value to find in cGy
    :param Beam: None sets beams to sum to Beamset fractional dose_value
                 <str_Beam> creates unique DSP for each beam for each beam's maximum
    :return: a list of [x, y, z] coordinates on the dose grid
    """
    # Get the MU weights of each beam
    tot = 0.
    for b in beam_set.Beams:
        tot += b.BeamMU

    if Beam is None:
        # Search the fractional dose grid
        # The dose grid is stored by RS as a numpy array
        pd = beam_set.FractionDose.DoseValues.DoseData
    else:
        # Find the right beam
        beam_found = False
        for b in beam_set.FractionDose.BeamDoses:
            if b.ForBeam.Name == Beam:
                pd = b.DoseValues.DoseData
                beam_found = True
        if not beam_found:
            print('No beam match for name provided')

    # The dose grid is stored [z: I/S, y: P/A, x: R/L]
    pd_np = pd.swapaxes(0, 2)

    if dose_per_fraction is None:
        rx = np.amax(pd_np)
    else:
        rx = dose_per_fraction

    logging.debug('rx = '.format(rx))

    xpos = None
    tolerance = 5.0e-2
    # beam_set = get_current('BeamSet')
    # plan = connect.get_current('Plan')

    xmax = plan.TreatmentCourse.TotalDose.InDoseGrid.NrVoxels.x
    ymax = plan.TreatmentCourse.TotalDose.InDoseGrid.NrVoxels.y
    xcorner = plan.TreatmentCourse.TotalDose.InDoseGrid.Corner.x
    ycorner = plan.TreatmentCourse.TotalDose.InDoseGrid.Corner.y
    zcorner = plan.TreatmentCourse.TotalDose.InDoseGrid.Corner.z
    xsize = plan.TreatmentCourse.TotalDose.InDoseGrid.VoxelSize.x
    ysize = plan.TreatmentCourse.TotalDose.InDoseGrid.VoxelSize.y
    zsize = plan.TreatmentCourse.TotalDose.InDoseGrid.VoxelSize.z

    if np.amax(pd_np) < rx:
        print
        'max = ', str(max(pd))
        print
        'target = ', str(rx)
        raise ValueError('max beam dose is too low')

    # rx_points = np.empty((0, 3), dtype=np.int)
    rx_points = np.argwhere(abs(rx - pd_np) <= tolerance)
    print("Shape of rx_points {}".format(rx_points.shape))

    # for (x, y, z), value in np.ndenumerate(pd_np):
    #    if rx - tolerance < value < rx + tolerance:
    #        rx_points = np.append(rx_points, np.array([[x, y, z]]), axis=0)
    #        print('dose = {}'.format(value))
    #        xpos = x * xsize + xcorner + xsize/2
    #        ypos = y * ysize + ycorner + ysize/2
    #        zpos = z * zsize + zcorner + zsize/2
    #        print 'corner = {0}, {1}, {2}'.format(xcorner,ycorner,zcorner)
    #        print 'x, y, z = {0}, {1}, {2}'.format(x * xsize, y * ysize, z * zsize)
    #        print 'x, y, z positions = {0}, {1}, {2}'.format(xpos,ypos,zpos)
    #        # return [xpos, ypos, zpos]
    # break

    matches = np.empty(np.size(rx_points, 0))

    for b in beam_set.FractionDose.BeamDoses:
        pd = np.array(b.DoseValues.DoseData)
        # The dose grid is stored [z: I/S, y: P/A, x: R/L]
        pd = pd.swapaxes(0, 2)
        # Numpy does evaluation of advanced indicies column wise:
        # pd[sheets, columns, rows]
        matches += abs(pd[rx_points[:, 0], rx_points[:, 1], rx_points[:, 2]] / rx -
                       b.ForBeam.BeamMU / tot)

    min_i = np.argmin(matches)
    xpos = rx_points[min_i, 0] * xsize + xcorner + xsize / 2
    ypos = rx_points[min_i, 1] * ysize + ycorner + ysize / 2
    zpos = rx_points[min_i, 2] * zsize + zcorner + zsize / 2
    print
    'x, y, z positions = {0}, {1}, {2}'.format(xpos, ypos, zpos)
    return [xpos, ypos, zpos]


def set_dsp(plan, beam_set):
    rx = beam_set.Prescription.PrimaryDosePrescription.DoseValue
    fractions = beam_set.FractionationPattern.NumberOfFractions
    if rx is None:
        raise ValueError('A Prescription must be set.')
    else:
        rx = rx / fractions

    dsp_pos = find_dsp(plan=plan, beam_set=beam_set, dose_per_fraction=rx)

    if dsp_pos:
        dsp_name = beam_set.DicomPlanLabel
        beam_set.CreateDoseSpecificationPoint(Name=dsp_name,
                                              Coordinates={'x': dsp_pos[0],
                                                           'y': dsp_pos[1],
                                                           'z': dsp_pos[2]})
    else:
        raise ValueError('No DSP was set, check execution details for clues.')

    # TODO: set this one up as an optional iteration for the case of multiple beams and multiple DSP's

    for i, beam in enumerate(beam_set.Beams):
        beam.SetDoseSpecificationPoint(Name=dsp_name)

    algorithm = beam_set.FractionDose.DoseValues.AlgorithmProperties.DoseAlgorithm
    # print "\n\nComputing Dose..."
    beam_set.ComputeDose(DoseAlgorithm=algorithm, ForceRecompute='TRUE')


def load_beams_xml(filename, beamset_name, path):
    """Load a beamset from the file located in the path in the filename:
    :param filename: The name of the xml file housing the beamset to be loaded
    :param beamset_name: name of the beamset (element) to load
    :param path: path to the xml file
    :return beams: a list of objects of type Beam"""

    beam_elements = Beams.select_element(set_level='beamset',
                                         set_type=None,
                                         set_elements='beam',
                                         set_level_name=beamset_name,
                                         filename=filename,
                                         folder=path,verbose_logging=True)

    beams = []
    for et_beamsets in beam_elements:
        beam_nodes = et_beamsets.findall('./beam')
        for b in beam_nodes:
            beam = Beam()
            beam.number = int(b.find('BeamNumber').text)
            beam.name = str(b.find('Name').text)
            beam.technique = str(b.find('DeliveryTechnique').text)
            beam.energy = int(b.find('Energy').text)
            beam.gantry_start_angle = float(b.find('GantryAngle').text)
            beam.gantry_stop_angle = float(b.find('GantryStopAngle').text)
            beam.rotation_dir = str(b.find('ArcRotationDirection').text)
            beam.collimator_angle = float(b.find('CollimatorAngle').text)
            beam.couch_angle = float(b.find('CouchAngle').text)
            beams.append(beam)
    return beams


def check_beam_limits(beam_name, plan, beamset, limit, change=False, verbose_logging=True):
    """
    Check the current locked limit on the beams and modify the optimization limit
    :param beam_name: name of beam to be modified
    :param plan: current plan
    :param beamset: current beamset
    :param limit: list of four limit [x1, x2, y1, y2]
    :param change: change the beam limit True/False
    :param verbose_logging: turn on (True) or off (False) extensive debugging messages
    :return: success: True if limits changed or limit is satisfied by current beam limits
    """
    # Find the optimization index corresponding to this beamset
    opt_index = PlanOperations.find_optimization_index(plan=plan, beamset=beamset, verbose_logging=verbose_logging)
    plan_optimization_parameters = plan.PlanOptimizations[opt_index].OptimizationParameters
    for tss in plan_optimization_parameters.TreatmentSetupSettings:
        if tss.ForTreatmentSetup.DicomPlanLabel == beamset.DicomPlanLabel:
            ts_settings = tss
            if verbose_logging:
                logging.debug('TreatmentSettings matching {} found'.format(beamset.DicomPlanLabel))
            break
        else:
            continue

    # Track whether the input beam_name is found in the list of beams belonging to this optimization.
    beam_found = False
    for b in ts_settings.BeamSettings:

        if b.ForBeam.Name == beam_name:
            beam_found = True
            current_beam = b

        else:
            continue

    if not beam_found:
        logging.warning('Beam {} not found in beam list from {}'.format(
            beam_name, beamset.DicomPlanLabel))
        sys.exit('Could not find a beam match for setting aperture limits')

    # Check if aperture limit exist.
    if current_beam.ForBeam.BeamMU > 0:
        if verbose_logging:
            logging.debug('Beam has MU. Changing jaw limit with an optimized beam is not possible without reset')
        return False
    else:
        # Check for existing aperture limit
        try:
            current_limits = current_beam.BeamApertureLimit
            if current_limits != 'NoLimit':
                existing_limits = [current_beam.ForBeam.InitialJawPositions[0],
                                   current_beam.ForBeam.InitialJawPositions[1],
                                   current_beam.ForBeam.InitialJawPositions[2],
                                   current_beam.ForBeam.InitialJawPositions[3]]
                if verbose_logging:
                    logging.debug(('aperture limits found on beam {} of initial jaw positions: x1 = {}, ' +
                                   'x2 = {}, y1 = {}, y2 = {}')
                                  .format(beam_name, existing_limits[0], existing_limits[1],
                                          existing_limits[2], existing_limits[3]))
            else:
                existing_limits = [None]*4
                if verbose_logging:
                    logging.debug('No limits currently exist on beam {}'.format(beam_name))

        except AttributeError:
            logging.debug('no existing aperture limits on beam {}'.format(beam_name))
            current_limits = None
            existing_limits = [None] * 4

        if current_limits == 'NoLimit':
            modified_limit = limit
            limits_met = False
            if verbose_logging:
                logging.info(('No jaw limits found on Beam {}: Jaw limits should be '
                              'x1 = {}, x2 = {}, y1 = {}, y2 = {}')
                             .format(beam_name,
                                     modified_limit[0],
                                     modified_limit[1],
                                     modified_limit[2],
                                     modified_limit[3]))

        else:
            x1 = existing_limits[0]
            x2 = existing_limits[1]
            y1 = existing_limits[2]
            y2 = existing_limits[3]
            if all([limit[0] <= x1, limit[1] >= x2, limit[2] <= y1, limit[3] >= y2]):
                limits_met = True
            else:
                limits_met = False
                modified_limit = [max(x1, limit[0]),
                                  min(x2, limit[1]),
                                  max(y1, limit[2]),
                                  min(y2, limit[3])]
                if verbose_logging:
                    logging.info(('Jaw limits found on Beam {}: Jaw limits should be changed '
                                  'x1: {} => {}, x2: {} => {}, y1: {} => {}, y2: {} => {}')
                                 .format(beam_name,
                                         limit[0], modified_limit[0],
                                         limit[1], modified_limit[1],
                                         limit[2], modified_limit[2],
                                         limit[3], modified_limit[3]))

        if not limits_met:
            if change:
                current_beam.EditBeamOptimizationSettings(
                    JawMotion='Use limits as max',
                    LeftJaw=modified_limit[0],
                    RightJaw=modified_limit[1],
                    TopJaw=modified_limit[2],
                    BottomJaw=modified_limit[3],
                    SelectCollimatorAngle='False',
                    AllowBeamSplit='False',
                    OptimizationTypes=['SegmentOpt', 'SegmentMU'])
                logging.info('Beam {}: Changed jaw limits x1: {} => {}, x2: {} = {}, y1: {} => {}, y2: {} => {}'
                             .format(beam_name,
                                     existing_limits[0], current_beam.ForBeam.InitialJawPositions[0],
                                     existing_limits[1], current_beam.ForBeam.InitialJawPositions[1],
                                     existing_limits[2], current_beam.ForBeam.InitialJawPositions[2],
                                     existing_limits[3], current_beam.ForBeam.InitialJawPositions[3]))
                return True
            else:
                logging.info(('Aperture check shows that limit on {} are not current. Limits should be '
                              'x1 = {}, x2 = {}, y1 = {}, y2 = {}').format(beam_name,
                                                                           modified_limit[0],
                                                                           modified_limit[1],
                                                                           modified_limit[2],
                                                                           modified_limit[3]))
                return False
        else:
            logging.debug('Limits met, no changes in aperture needed')
            return True