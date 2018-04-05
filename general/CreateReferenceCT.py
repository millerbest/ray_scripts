""" Create Reference CT
    
    This script generates a homogeneous phantom CT (0 HU) padded by empty voxels. The 
    DICOM origin is set to the top (anterior) center of the image. The image size and 
    dimensions are specified below. The resulting DICOM images are saved to the provided 
    directory using the format ct_###.dcm.
    
    This script uses the pydicom and numpy packages. For installation instructions, see 
    http://pydicom.readthedocs.io/en/stable/getting_started.html and 
    https://scipy.org/install.html, respectively. Copies of both packages are included as
    submodules within this repository. 
    
    This program is free software: you can redistribute it and/or modify it under
    the terms of the GNU General Public License as published by the Free Software
    Foundation, either version 3 of the License, or (at your option) any later version.
    
    This program is distributed in the hope that it will be useful, but WITHOUT
    ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
    FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
    
    You should have received a copy of the GNU General Public License along with
    this program. If not, see <http://www.gnu.org/licenses/>.
    """

__author__ = 'Mark Geurts'
__contact__ = 'mark.w.geurts@gmail.com'
__date__ = '2018-02-07'

__version__ = '1.0.1'
__status__ = 'Development'
__deprecated__ = False
__reviewer__ = 'N/A'

__reviewed__ = 'YYYY-MM-DD'
__maintainer__ = 'Mark Geurts'

__email__ =  'mark.w.geurts@gmail.com'
__license__ = 'GPLv3'
__copyright__ = 'Copyright (C) 2018, University of Wisconsin Board of Regents'

# Specify import statements
import os
from numpy import zeros, uint16
import datetime
from logging import info, error
from pydicom.dataset import Dataset
from pydicom.uid import generate_uid

# If running from Windows (with IronPython installed in the location specified below) 
# prompt user to select folder, otherwise, ask them via raw_input()
try:
    ipy = r'c:\Program Files (x86)\IronPython 2.7.1\ipy.exe'
    str = 'Select folder to export CT to:'
    import subprocess
    path = subprocess.check_output('"{}" {} "{}"'.format(ipy, \
        os.path.join(os.path.dirname(os.path.abspath(__file__)), \
        '..\library\FolderBrowser.py'), str))
except:
    path = raw_input('Enter path to write CT to: ')

# Declare image size and resolution (in mm), IEC [X,Z,Y]
size = [651,401,651]
res = [1,1,1]

# Get current date, time
now = datetime.datetime.now()    

# Create new dict, and add basic image attributes
ds = Dataset()
ds.file_meta = Dataset()
ds.file_meta.TransferSyntaxUID = '1.2.840.10008.1.2'
ds.file_meta.ImplementationClassUID = '1.2.40.0.13.1.1'
ds.file_meta.ImplementationVersionName = 'dcm4che-2.0'
ds.SpecificCharacterSet = 'ISO_IR 100'
ds.file_meta.MediaStorageSOPClassUID = '1.2.840.10008.5.1.4.1.1.2'
ds.Modality = 'CT'
ds.SOPClassUID = ds.file_meta.MediaStorageSOPClassUID
ds.is_little_endian = True
ds.is_implicit_VR = True
ds.RescaleIntercept = -1024
ds.RescaleSlope = 1
ds.InstanceCreationDate = '{0}{1:0>2}{2:0>2}'.format(now.year, now.month, now.day)
ds.InstanceCreationTime = '{0:0>2}{1:0>2}{2:0>2}'.format(now.hour, now.minute, now.second)
ds.StudyDate = '{0}{1:0>2}{2:0>2}'.format(now.year, now.month, now.day)
ds.StudyTime = '{0:0>2}{1:0>2}{2:0>2}'.format(now.hour, now.minute, now.second)
ds.AcquisitionDate = '{0}{1:0>2}{2:0>2}'.format(now.year, now.month, now.day)
ds.AcquisitionTime = '{0:0>2}{1:0>2}{2:0>2}'.format(now.hour, now.minute, now.second)
ds.ImageType = 'ORIGINAL\PRIMARY\AXIAL'
ds.Manufacturer = 'pydicom'
ds.ManufacturerModelName = 'CreateReferenceCT'
ds.SoftwareVersion = '1.0'
ds.SeriesDescription = 'Uniform Phantom'
ds.PatientName = 'Water Phantom'
ds.PatientID = '{0}{1:0>2}{2:0>2}'.format(now.year, now.month, now.day)
ds.SliceThickness = res[2]
ds.StudyInstanceUID = generate_uid()
ds.SeriesInstanceUID = generate_uid()
ds.FrameOfReferenceUID = generate_uid()
ds.PatientPosition = 'HFS'
ds.ImageOrientationPatient = [1,0,0,0,1,0]
ds.ImagePositionPatient = [-((size[0]-1)*res[0])/2, -res[1]/2, ((size[2]-1)*res[2])/2]
ds.ImagesInAcquisition = size[2]
ds.SamplesPerPixel = 1
ds.PhotometricInterpretation = 'MONOCHROME2'
ds.Rows = size[1]
ds.Columns = size[0]
ds.PixelSpacing = [res[0],res[1]]
ds.BitsAllocated = 16
ds.BitsStored = 16
ds.HighBit = 15
ds.PixelRepresentation = 0

# Create padded image
img = zeros(shape=(size[1],size[0]), dtype=uint16)
for i in range(1, size[1]-1):
    for j in range(1, size[0]-1):
        img[i,j] = 1024
        
ds.PixelData = img.tostring()

# Loop through CT Images
for i in range(size[2]):

    # Generate unique IDs
    ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
    ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
    
    # Set position info for this image
    ds.SliceLocation = -((size[2]-1)*res[2])/2 + i * res[2]
    ds.ImagePositionPatient[2] = -ds.SliceLocation
    ds.InstanceNumber = i+1

    # Write CT image
    info('Writing image ct_{0:0>3}.dcm'.format(i+1))
    ds.save_as(os.path.normpath('{0}/ct_{1:0>3}.dcm'.format(path, i+1)))
