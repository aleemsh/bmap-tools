# -*- coding: utf-8 -*-
# vim: ts=4 sw=4 et ai si
#
# Copyright (c) 2012-2014 Intel, Inc.
# License: GPLv2
# Author: Artem Bityutskiy <artem.bityutskiy@linux.intel.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License, version 2,
# as published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.

"""
This test verifies the base bmap creation and copying API functionality. It
generates a random sparse file, then creates a bmap fir this file and copies it
to a different file using the bmap. Then it compares the original random sparse
file and the copy and verifies that they are identical.
"""

# Disable the following pylint recommendations:
#   * Too many public methods (R0904)
#   * Too many local variables (R0914)
#   * Too many statements (R0915)
# pylint: disable=R0904
# pylint: disable=R0914
# pylint: disable=R0915

import os
import tempfile
import filecmp
import itertools
import subprocess
from tests import helpers
from bmaptools import BmapHelpers, BmapCreate, Filemap

# This is a work-around for Centos 6
try:
    import unittest2 as unittest # pylint: disable=F0401
except ImportError:
    import unittest

class Error(Exception):
    """A class for exceptions generated by this test."""
    pass

def _compare_holes(file1, file2):
    """
    Make sure that files 'file1' and 'file2' have holes at the same places.
    The 'file1' and 'file2' arguments may be full file paths or file objects.
    """

    filemap1 = Filemap.filemap(file1)
    filemap2 = Filemap.filemap(file2)

    iterator1 = filemap1.get_unmapped_ranges(0, filemap1.blocks_cnt)
    iterator2 = filemap2.get_unmapped_ranges(0, filemap2.blocks_cnt)

    iterator = itertools.izip_longest(iterator1, iterator2)
    for range1, range2 in iterator:
        if range1 != range2:
            raise Error("mismatch for hole %d-%d, it is %d-%d in file2"
                        % (range1[0], range1[1], range2[0], range2[1]))


def _generate_compressed_files(file_path, delete=True):
    """
    This is a generator which yields compressed versions of a file
    'file_path'.

    The 'delete' argument specifies whether the compressed files that this
    generator yields have to be automatically deleted.
    """

    # Make sure the temporary files start with the same name as 'file_obj' in
    # order to simplify debugging.
    prefix = os.path.splitext(os.path.basename(file_path))[0] + '.'
    # Put the temporary files in the directory with 'file_obj'
    directory = os.path.dirname(file_path)

    compressors = [("bzip2",  None, ".bz2",   "-c -k"),
                   ("pbzip2", None, ".p.bz2", "-c -k"),
                   ("gzip",   None, ".gz",    "-c"),
                   ("pigz",   None, ".p.gz",  "-c -k"),
                   ("xz",     None, ".xz",    "-c -k"),
                   ("lzop",   None, ".lzo",   "-c -k"),
                   # The "-P -C /" trick is used to avoid silly warnings:
                   # "tar: Removing leading `/' from member names"
                   ("bzip2", "tar", ".tar.bz2", "-c -j -O -P -C /"),
                   ("gzip",  "tar", ".tar.gz",  "-c -z -O -P -C /"),
                   ("xz",    "tar", ".tar.xz",  "-c -J -O -P -C /"),
                   ("lzop",  "tar", ".tar.lzo", "-c --lzo -O -P -C /")]

    for decompressor, archiver, suffix, options in compressors:
        if not BmapHelpers.program_is_available(decompressor):
            continue
        if archiver and not BmapHelpers.program_is_available(archiver):
            continue

        tmp_file_obj = tempfile.NamedTemporaryFile('wb+', prefix=prefix,
                                                   delete=delete, dir=directory,
                                                   suffix=suffix)

        if archiver:
            args = archiver + " " + options + " " + file_path
        else:
            args = decompressor + " " + options + " " + file_path
        child_process = subprocess.Popen(args, shell=True,
                                         stderr=subprocess.PIPE,
                                         stdout=tmp_file_obj)
        child_process.wait()
        tmp_file_obj.flush()
        yield tmp_file_obj.name
        tmp_file_obj.close()

def _do_test(image, image_size, delete=True):
    """
    A basic test for the bmap creation and copying functionality. It first
    generates a bmap for file 'image', and then copies the sparse file to a
    different file, and then checks that the original file and the copy are
    identical.

    The 'image_size' argument is size of the image in bytes. The 'delete'
    argument specifies whether the temporary files that this function creates
    have to be automatically deleted.
    """

    # Make sure the temporary files start with the same name as 'image' in
    # order to simplify debugging.
    prefix = os.path.splitext(os.path.basename(image))[0] + '.'
    # Put the temporary files in the directory with the image
    directory = os.path.dirname(image)

    # Create and open a temporary file for a copy of the image
    f_copy = tempfile.NamedTemporaryFile("wb+", prefix=prefix,
                                        delete=delete, dir=directory,
                                        suffix=".copy")

    # Create and open 2 temporary files for the bmap
    f_bmap1 = tempfile.NamedTemporaryFile("w+", prefix=prefix,
                                          delete=delete, dir=directory,
                                          suffix=".bmap1")
    f_bmap2 = tempfile.NamedTemporaryFile("w+", prefix=prefix,
                                          delete=delete, dir=directory,
                                          suffix=".bmap2")

    image_chksum = helpers.calculate_chksum(image)

    #
    # Pass 1: generate the bmap, copy and compare
    #

    # Create bmap for the random sparse file
    creator = BmapCreate.BmapCreate(image, f_bmap1.name)
    creator.generate()

    helpers.copy_and_verify_image(image, f_copy.name, f_bmap1.name,
                                  image_chksum, image_size)

    # Make sure that holes in the copy are identical to holes in the random
    # sparse file.
    _compare_holes(image, f_copy.name)

    #
    # Pass 2: same as pass 1, but use file objects instead of paths
    #

    creator = BmapCreate.BmapCreate(image, f_bmap2)
    creator.generate()
    helpers.copy_and_verify_image(image, f_copy.name, f_bmap2.name,
                                  image_chksum, image_size)
    _compare_holes(image, f_copy.name)

    # Make sure the bmap files generated at pass 1 and pass 2 are identical
    assert filecmp.cmp(f_bmap1.name, f_bmap2.name, False)

    #
    # Pass 3: test compressed files copying with bmap
    #

    for compressed in _generate_compressed_files(image, delete=delete):
        helpers.copy_and_verify_image(compressed, f_copy.name,
                                      f_bmap1.name, image_chksum, image_size)

        # Test without setting the size
        helpers.copy_and_verify_image(compressed, f_copy.name, f_bmap1.name,
                                      image_chksum, None)

        # Append a "file:" prefixe to make BmapCopy use urllib
        compressed = "file:" + compressed
        helpers.copy_and_verify_image(compressed, f_copy.name, f_bmap1.name,
                                      image_chksum, image_size)
        helpers.copy_and_verify_image(compressed, f_copy.name, f_bmap1.name,
                                      image_chksum, None)

    #
    # Pass 5: copy without bmap and make sure it is identical to the original
    # file.

    helpers.copy_and_verify_image(image, f_copy.name, None, image_chksum,
                                  image_size)
    helpers.copy_and_verify_image(image, f_copy.name, None, image_chksum, None)

    #
    # Pass 6: test compressed files copying without bmap
    #

    for compressed in _generate_compressed_files(image, delete=delete):
        helpers.copy_and_verify_image(compressed, f_copy.name, f_bmap1.name,
                                      image_chksum, image_size)

        # Test without setting the size
        helpers.copy_and_verify_image(compressed, f_copy.name, f_bmap1.name,
                                      image_chksum, None)

        # Append a "file:" prefix to make BmapCopy use urllib
        helpers.copy_and_verify_image(compressed, f_copy.name, f_bmap1.name,
                                      image_chksum, image_size)
        helpers.copy_and_verify_image(compressed, f_copy.name, f_bmap1.name,
                                      image_chksum, None)

    # Close temporary files, which will also remove them
    f_copy.close()
    f_bmap1.close()
    f_bmap2.close()

class TestCreateCopy(unittest.TestCase):
    """
    The test class for this unit tests. Basically executes the '_do_test()'
    function for different sparse files.
    """

    def test(self): # pylint: disable=R0201
        """
        The test entry point. Executes the '_do_test()' function for files of
        different sizes, holes distribution and format.
        """

        # Delete all the test-related temporary files automatically
        delete = True
        # Create all the test-related temporary files in current directory
        directory = '.'

        iterator = helpers.generate_test_files(delete=delete,
                                               directory=directory)
        for f_image, image_size, _, _ in iterator:
            assert image_size == os.path.getsize(f_image.name)
            _do_test(f_image.name, image_size, delete=delete)
