package com.example.springwebtlias.controller;

import com.example.springwebtlias.pojo.Result;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

@RestController
@Slf4j
public class UploadController {

    @PostMapping("/upload")
    public Result upload(String name, Integer age, MultipartFile image)
    {
        log.info("name{},age{},image{}",name,age,image);
        return Result.success();
    }
}
